import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from redis.asyncio import Redis

from app.config import get_settings
from app.deps import AuthContext, resolve_auth
from app.errors import AppError

settings = get_settings()


def rate_limit_key(api_key_id: UUID) -> str:
    return f"ratelimit:{api_key_id}"


async def check_rate_limit(redis: Redis, api_key_id: UUID) -> tuple[bool, int, int, int]:
    now = time.time()
    window = settings.rate_limit_window_seconds
    limit = settings.rate_limit_requests
    key = rate_limit_key(api_key_id)
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window)
    _, _, count, _ = await pipe.execute()
    remaining = max(limit - int(count), 0)
    reset = int(now) + window
    allowed = int(count) <= limit
    retry_after = window if not allowed else 0
    return allowed, remaining, reset, retry_after


async def enforce_rate_limit(
    request: Request,
    response: Response,
    auth: Annotated[AuthContext, Depends(resolve_auth)],
) -> AuthContext:
    if auth.api_key_id is None:
        return auth
    redis: Redis = request.app.state.redis
    allowed, remaining, reset, retry_after = await check_rate_limit(redis, auth.api_key_id)
    response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset)
    if not allowed:
        raise AppError(
            "rate_limited",
            "Rate limit exceeded",
            429,
            details={"retry_after": retry_after},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(settings.rate_limit_requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset),
            },
        )
    return auth


RateLimitDep = Annotated[AuthContext, Depends(enforce_rate_limit)]
