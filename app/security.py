import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, role: str, merchant_id: UUID | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    if merchant_id is not None:
        payload["merchant_id"] = str(merchant_id)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def generate_api_key() -> tuple[str, str, str]:
    raw = secrets.token_urlsafe(32)
    full = f"{settings.api_key_prefix}{raw}"
    prefix = full[:16]
    return full, prefix, hash_api_key(full)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def hmac_sign(secret: str, timestamp: str, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_verify(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    expected = hmac_sign(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def request_body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
