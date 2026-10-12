import pytest


@pytest.mark.asyncio
async def test_idempotency_replay_and_conflict(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    body = {
        "customer_id": customer["id"],
        "amount_minor": 2500,
        "currency": "INR",
    }
    key_headers = {**headers, "Idempotency-Key": "idem-1"}
    first = await client.post("/payments", headers=key_headers, json=body)
    assert first.status_code == 201
    payment_id = first.json()["id"]

    second = await client.post("/payments", headers=key_headers, json=body)
    assert second.status_code == 201
    assert second.json()["id"] == payment_id

    conflict = await client.post(
        "/payments",
        headers=key_headers,
        json={**body, "amount_minor": 9999},
    )
    assert conflict.status_code == 422
    assert conflict.json()["code"] == "idempotency_conflict"
