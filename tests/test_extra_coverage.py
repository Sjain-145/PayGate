from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.base import apply_filters, paginate_stmt
from app.db import close_redis, get_db, get_redis
from app.errors import AppError, register_exception_handlers
from app.idempotency import IdempotentReplay
from app.main import app
from app.models import Payment, PaymentStatus
from app.webhooks import deliver_webhook, generate_webhook_secret


@pytest.mark.asyncio
async def test_x_api_key_header(client, merchant_bundle, customer):
    resp = await client.get(
        "/payments",
        headers={"X-API-Key": merchant_bundle["api_key"]},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_invalid(client, merchant_bundle):
    resp = await client.post(
        "/auth/login", json={"email": "admin@test.com", "password": "wrongpass"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_user_token(client, merchant_bundle):
    resp = await client.get("/auth/me", headers=merchant_bundle["api_headers"])
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refund_requires_captured(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    create = await client.post(
        "/payments",
        headers=headers,
        json={"customer_id": customer["id"], "amount_minor": 1000, "currency": "INR"},
    )
    pid = create.json()["id"]
    resp = await client.post(
        "/refunds", headers=headers, json={"payment_id": pid, "amount_minor": 100}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_refund_missing_payment(client, merchant_bundle):
    headers = merchant_bundle["api_headers"]
    resp = await client.post(
        "/refunds",
        headers=headers,
        json={"payment_id": str(uuid4()), "amount_minor": 100},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pagination_cursor(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    for i in range(3):
        await client.post(
            "/payments",
            headers=headers,
            json={
                "customer_id": customer["id"],
                "amount_minor": 1000 + i,
                "currency": "INR",
            },
        )
    first = await client.get("/payments?limit=2", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]
    second = await client.get(f"/payments?limit=2&cursor={body['next_cursor']}", headers=headers)
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_get_redis_and_close():
    redis = await get_redis()
    assert await redis.ping()
    await close_redis()
    redis2 = await get_redis()
    assert await redis2.ping()
    await close_redis()


@pytest.mark.asyncio
async def test_get_db_generator(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db as db_module

    db_module.SessionLocal = async_sessionmaker(
        db_engine, expire_on_commit=False, class_=AsyncSession
    )
    gen = get_db()
    session = await gen.__anext__()
    assert session is not None
    await gen.aclose()


@pytest.mark.asyncio
async def test_idempotent_replay_handler():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test"):
        # invoke handler directly
        from app.main import idempotent_replay_handler

        resp = await idempotent_replay_handler(
            None,
            IdempotentReplay(200, {"ok": True}),  # type: ignore[arg-type]
        )
        assert resp.status_code == 200


def test_apply_filters_ops():
    stmt = select(Payment)
    filtered = apply_filters(
        stmt,
        Payment,
        {
            "status": PaymentStatus.created,
            "amount_minor__gte": 10,
            "amount_minor__lte": 100,
            "amount_minor__gt": 5,
            "amount_minor__lt": 200,
            "missing": None,
        },
    )
    assert filtered is not None
    paged = paginate_stmt(filtered, Payment, cursor=None, limit=5)
    assert paged is not None


def test_generate_webhook_secret():
    assert len(generate_webhook_secret()) > 10


def test_deliver_webhook_task():
    with patch("app.webhooks.asyncio.run") as run:
        deliver_webhook(str(uuid4()))
        run.assert_called_once()


@pytest.mark.asyncio
async def test_http_exception_and_unhandled():
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.requests import Request

    probe = FastAPI()
    register_exception_handlers(probe)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    request = Request(scope)

    r1 = await probe.exception_handlers[StarletteHTTPException](
        request, StarletteHTTPException(status_code=404, detail="nope")
    )
    assert isinstance(r1, JSONResponse)
    assert r1.status_code == 404

    r2 = await probe.exception_handlers[Exception](request, RuntimeError("x"))
    assert r2.status_code == 500

    r3 = await probe.exception_handlers[AppError](request, AppError("x", "y", 400))
    assert r3.status_code == 400


@pytest.mark.asyncio
async def test_merchant_forbidden_cross_tenant(client, merchant_bundle):
    headers = merchant_bundle["merchant_headers"]
    resp = await client.get(f"/merchants/{uuid4()}", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_delivery_get_404(client, merchant_bundle):
    headers = merchant_bundle["api_headers"]
    resp = await client.get(f"/webhook-deliveries/{uuid4()}", headers=headers)
    assert resp.status_code == 404
