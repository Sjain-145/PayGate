import pytest


async def _create_payment(client, headers, customer_id, amount=5000, key=None):
    h = dict(headers)
    if key:
        h["Idempotency-Key"] = key
    return await client.post(
        "/payments",
        headers=h,
        json={
            "customer_id": customer_id,
            "amount_minor": amount,
            "currency": "INR",
            "description": "test",
        },
    )


@pytest.mark.asyncio
async def test_payment_lifecycle(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    create = await _create_payment(client, headers, customer["id"])
    assert create.status_code == 201
    payment = create.json()
    assert payment["status"] == "created"
    assert "risk_score" in payment
    pid = payment["id"]

    authz = await client.post(f"/payments/{pid}/authorize", headers=headers)
    assert authz.status_code == 200
    assert authz.json()["status"] == "authorized"

    capture = await client.post(f"/payments/{pid}/capture", headers=headers)
    assert capture.status_code == 200
    assert capture.json()["status"] == "captured"

    listed = await client.get("/payments", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("steps", "bad_action"),
    [
        ([], "capture"),
        (["authorize", "capture"], "cancel"),
        (["cancel"], "authorize"),
    ],
)
async def test_invalid_transitions(client, merchant_bundle, customer, steps, bad_action):
    headers = merchant_bundle["api_headers"]
    create = await _create_payment(client, headers, customer["id"])
    pid = create.json()["id"]
    for step in steps:
        resp = await client.post(f"/payments/{pid}/{step}", headers=headers)
        assert resp.status_code == 200
    bad = await client.post(f"/payments/{pid}/{bad_action}", headers=headers)
    assert bad.status_code == 409
    assert bad.json()["code"] == "invalid_transition"


@pytest.mark.asyncio
async def test_list_filters(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    await _create_payment(client, headers, customer["id"], amount=1000)
    await _create_payment(client, headers, customer["id"], amount=9000)
    resp = await client.get("/payments?amount_minor__gte=5000", headers=headers)
    assert resp.status_code == 200
    assert all(item["amount_minor"] >= 5000 for item in resp.json()["items"])
