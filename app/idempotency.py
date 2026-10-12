import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.deps import AuthContext, resolve_auth
from app.errors import AppError
from app.security import request_body_hash

settings = get_settings()


class IdempotentReplay(Exception):
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


def idempotency_redis_key(merchant_id: UUID, key: str) -> str:
    return f"idempotency:{merchant_id}:{key}"


async def get_cached_response(redis: Redis, merchant_id: UUID, key: str) -> dict | None:
    raw = await redis.get(idempotency_redis_key(merchant_id, key))
    return json.loads(raw) if raw else None


async def store_response(
    redis: Redis,
    merchant_id: UUID,
    key: str,
    request_hash: str,
    status_code: int,
    body: Any,
) -> None:
    payload = {"request_hash": request_hash, "status_code": status_code, "body": body}
    await redis.set(
        idempotency_redis_key(merchant_id, key),
        json.dumps(payload, default=str),
        ex=settings.idempotency_ttl_seconds,
    )


async def enforce_idempotency(
    request: Request,
    auth: Annotated[AuthContext, Depends(resolve_auth)],
) -> None:
    if request.method != "POST":
        return
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    if auth.merchant_id is None:
        return

    body = await request.body()
    body_hash = request_body_hash(body)
    redis: Redis = request.app.state.redis
    cached = await get_cached_response(redis, auth.merchant_id, key)
    if cached:
        if cached["request_hash"] != body_hash:
            raise AppError(
                "idempotency_conflict",
                "Idempotency-Key reused with a different request body",
                422,
            )
        raise IdempotentReplay(cached["status_code"], cached["body"])

    request.state.idempotency_key = key
    request.state.idempotency_hash = body_hash
    request.state.idempotency_merchant_id = auth.merchant_id


IdempotencyDep = Annotated[None, Depends(enforce_idempotency)]


class IdempotencyStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        key = getattr(request.state, "idempotency_key", None)
        merchant_id = getattr(request.state, "idempotency_merchant_id", None)
        body_hash = getattr(request.state, "idempotency_hash", None)
        redis: Redis | None = getattr(request.app.state, "redis", None)
        if not key or not merchant_id or not body_hash or redis is None:
            return response
        if not (200 <= response.status_code < 300):
            return response

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk if isinstance(chunk, bytes) else chunk.encode()
        try:
            parsed = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            parsed = {"raw": response_body.decode(errors="replace")}
        await store_response(redis, merchant_id, key, body_hash, response.status_code, parsed)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(status_code=response.status_code, content=parsed, headers=headers)
