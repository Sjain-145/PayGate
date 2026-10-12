from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, get_redis
from app.errors import AppError
from app.models import ApiKey, Role, User
from app.security import decode_access_token, hash_api_key

bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    role: Role
    user_id: UUID | None = None
    merchant_id: UUID | None = None
    api_key_id: UUID | None = None


async def resolve_auth(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> AuthContext:
    raw_key = x_api_key
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        if token.startswith("pg_") or token.startswith("pg_live_"):
            raw_key = token
        else:
            try:
                payload = decode_access_token(token)
            except PyJWTError as exc:
                raise AppError("unauthorized", "Invalid token", 401) from exc
            role = Role(payload["role"])
            merchant_id = UUID(payload["merchant_id"]) if payload.get("merchant_id") else None
            ctx = AuthContext(
                role=role,
                user_id=UUID(payload["sub"]),
                merchant_id=merchant_id,
            )
            request.state.auth = ctx
            return ctx

    if raw_key:
        key_hash = hash_api_key(raw_key)
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise AppError("unauthorized", "Invalid API key", 401)
        ctx = AuthContext(
            role=Role.merchant,
            merchant_id=api_key.merchant_id,
            api_key_id=api_key.id,
        )
        request.state.auth = ctx
        request.state.api_key_id = api_key.id
        request.state.merchant_id = api_key.merchant_id
        return ctx

    raise AppError("unauthorized", "Authentication required", 401)


def require(*roles: Role | str):
    allowed = {Role(r) if isinstance(r, str) else r for r in roles}

    async def dependency(auth: Annotated[AuthContext, Depends(resolve_auth)]) -> AuthContext:
        if auth.role not in allowed:
            raise AppError("forbidden", "Insufficient permissions", 403)
        return auth

    return dependency


async def get_current_user(
    auth: Annotated[AuthContext, Depends(resolve_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if auth.user_id is None:
        raise AppError("unauthorized", "User token required", 401)
    user = await db.get(User, auth.user_id)
    if user is None or not user.is_active:
        raise AppError("unauthorized", "User not found", 401)
    return user


RedisDep = Annotated[Redis, Depends(get_redis)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
AuthDep = Annotated[AuthContext, Depends(resolve_auth)]
