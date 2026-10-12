import asyncio

import pytest


async def _captured_payment(client, headers, customer_id, amount=10000):
    create = await client.post(
        "/payments",
        headers=headers,
        json={"customer_id": customer_id, "amount_minor": amount, "currency": "INR"},
    )
    pid = create.json()["id"]
    await client.post(f"/payments/{pid}/authorize", headers=headers)
    await client.post(f"/payments/{pid}/capture", headers=headers)
    return pid


@pytest.mark.asyncio
async def test_partial_and_full_refund(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    pid = await _captured_payment(client, headers, customer["id"], 10000)
    r1 = await client.post(
        "/refunds",
        headers=headers,
        json={"payment_id": pid, "amount_minor": 4000, "reason": "partial"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/refunds",
        headers=headers,
        json={"payment_id": pid, "amount_minor": 6000},
    )
    assert r2.status_code == 201
    over = await client.post(
        "/refunds",
        headers=headers,
        json={"payment_id": pid, "amount_minor": 1},
    )
    assert over.status_code == 409
    assert over.json()["code"] == "refund_exceeds_capture"


@pytest.mark.asyncio
async def test_concurrent_refund_over_limit(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    pid = await _captured_payment(client, headers, customer["id"], 10000)

    async def refund(amount: int):
        return await client.post(
            "/refunds",
            headers=headers,
            json={"payment_id": pid, "amount_minor": amount},
        )

    results = await asyncio.gather(refund(7000), refund(7000))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409]
