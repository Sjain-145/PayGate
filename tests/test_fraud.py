from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_fraud_flag_on_high_score(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    with patch("app.routers.payments.score_payment", return_value=(0.95, True)):
        resp = await client.post(
            "/payments",
            headers=headers,
            json={
                "customer_id": customer["id"],
                "amount_minor": 99999999,
                "currency": "INR",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["risk_score"] == 0.95
    assert body["fraud_flagged"] is True


@pytest.mark.asyncio
async def test_fraud_score_present(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    resp = await client.post(
        "/payments",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "amount_minor": 1200,
            "currency": "INR",
        },
    )
    assert resp.status_code == 201
    assert 0.0 <= resp.json()["risk_score"] <= 1.0
