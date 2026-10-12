import json
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import DeliveryStatus, WebhookDelivery
from app.security import hmac_verify
from app.webhooks import enqueue_event


class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    captured: dict = {}
    status_code: int = 200

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, content=None, headers=None, **kwargs):
        type(self).captured = {"url": url, "content": content, "headers": headers}
        return _FakeResp(self.status_code, "fail" if self.status_code >= 400 else "ok")


@pytest.mark.asyncio
async def test_webhook_signature_and_success(client_with_webhooks, merchant_bundle, db_session):
    client = client_with_webhooks
    headers = merchant_bundle["api_headers"]
    cust = await client.post(
        "/customers",
        headers=headers,
        json={"email": "hookcust@test.com", "name": "Hook"},
    )
    assert cust.status_code == 201
    customer = cust.json()

    endpoint = await client.post(
        "/webhook-endpoints",
        headers=headers,
        json={"url": "https://example.test/hooks", "secret": "supersecretkey", "events": ["*"]},
    )
    assert endpoint.status_code == 201

    _FakeAsyncClient.captured = {}
    _FakeAsyncClient.status_code = 200
    with patch("app.webhooks.httpx.AsyncClient", _FakeAsyncClient):
        pay = await client.post(
            "/payments",
            headers=headers,
            json={
                "customer_id": customer["id"],
                "amount_minor": 1500,
                "currency": "INR",
            },
        )
        assert pay.status_code == 201, pay.text

    captured = _FakeAsyncClient.captured
    assert captured["url"] == "https://example.test/hooks"
    assert hmac_verify(
        "supersecretkey",
        captured["headers"]["X-Timestamp"],
        captured["content"],
        captured["headers"]["X-Signature"],
    )
    body = json.loads(captured["content"])
    assert body["type"] == "payment.created"

    result = await db_session.execute(select(WebhookDelivery))
    delivery = result.scalars().first()
    assert delivery is not None
    assert delivery.status == DeliveryStatus.success


@pytest.mark.asyncio
async def test_webhook_retry_then_failure(client_with_webhooks, merchant_bundle, db_session):
    client = client_with_webhooks
    headers = merchant_bundle["api_headers"]
    endpoint = await client.post(
        "/webhook-endpoints",
        headers=headers,
        json={"url": "https://example.test/fail", "secret": "supersecretkey"},
    )
    assert endpoint.status_code == 201
    merchant_id = merchant_bundle["merchant"].id

    _FakeAsyncClient.captured = {}
    _FakeAsyncClient.status_code = 500
    with patch("app.webhooks.httpx.AsyncClient", _FakeAsyncClient):
        ids = await enqueue_event(merchant_id, "payment.created", {"ok": False})
    assert len(ids) == 1
    delivery = await db_session.get(WebhookDelivery, ids[0])
    await db_session.refresh(delivery)
    assert delivery is not None
    assert delivery.status == DeliveryStatus.failed
    assert delivery.attempt_count == 3
    assert len(delivery.attempts) == 3
