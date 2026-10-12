import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_rate_limit_returns_429(client, merchant_bundle):
    headers = merchant_bundle["api_headers"]
    settings = get_settings()
    original = settings.rate_limit_requests
    settings.rate_limit_requests = 3
    try:
        last = None
        for _ in range(5):
            last = await client.get("/payments", headers=headers)
        assert last is not None
        assert last.status_code == 429
        assert last.json()["code"] == "rate_limited"
        assert "Retry-After" in last.headers
        assert "X-RateLimit-Limit" in last.headers
        assert "X-RateLimit-Remaining" in last.headers
    finally:
        settings.rate_limit_requests = original
