import pytest


@pytest.mark.asyncio
async def test_merchant_crud_and_api_keys(client, merchant_bundle):
    admin = merchant_bundle["admin_headers"]
    created = await client.post(
        "/merchants",
        headers=admin,
        json={"name": "New Co", "email": "newco@test.com"},
    )
    assert created.status_code == 201
    mid = created.json()["id"]

    got = await client.get(f"/merchants/{mid}", headers=admin)
    assert got.status_code == 200

    patched = await client.patch(f"/merchants/{mid}", headers=admin, json={"name": "New Co 2"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "New Co 2"

    key = await client.post(
        f"/merchants/{mid}/api-keys",
        headers=admin,
        json={"name": "primary"},
    )
    assert key.status_code == 201
    assert key.json()["api_key"].startswith("pg_live_")

    keys = await client.get(f"/merchants/{mid}/api-keys", headers=admin)
    assert keys.status_code == 200
    assert len(keys.json()) >= 1


@pytest.mark.asyncio
async def test_register_user(client, merchant_bundle):
    admin = merchant_bundle["admin_headers"]
    mid = merchant_bundle["merchant"].id
    resp = await client.post(
        "/auth/register",
        headers=admin,
        json={
            "email": "newuser@test.com",
            "password": "password123",
            "role": "merchant",
            "merchant_id": str(mid),
        },
    )
    assert resp.status_code == 201
    dup = await client.post(
        "/auth/register",
        headers=admin,
        json={
            "email": "newuser@test.com",
            "password": "password123",
            "role": "merchant",
            "merchant_id": str(mid),
        },
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_customer_get_and_list(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    got = await client.get(f"/customers/{customer['id']}", headers=headers)
    assert got.status_code == 200
    listed = await client.get("/customers", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) >= 1


@pytest.mark.asyncio
async def test_webhook_endpoint_crud(client, merchant_bundle):
    headers = merchant_bundle["api_headers"]
    created = await client.post(
        "/webhook-endpoints",
        headers=headers,
        json={"url": "https://example.test/a", "secret": "abcdefgh"},
    )
    assert created.status_code == 201
    eid = created.json()["id"]
    got = await client.get(f"/webhook-endpoints/{eid}", headers=headers)
    assert got.status_code == 200
    patched = await client.patch(
        f"/webhook-endpoints/{eid}", headers=headers, json={"is_active": False}
    )
    assert patched.status_code == 200
    listed = await client.get("/webhook-endpoints", headers=headers)
    assert listed.status_code == 200
    deliveries = await client.get("/webhook-deliveries", headers=headers)
    assert deliveries.status_code == 200


@pytest.mark.asyncio
async def test_refund_list_and_get(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    create = await client.post(
        "/payments",
        headers=headers,
        json={"customer_id": customer["id"], "amount_minor": 5000, "currency": "INR"},
    )
    pid = create.json()["id"]
    await client.post(f"/payments/{pid}/authorize", headers=headers)
    await client.post(f"/payments/{pid}/capture", headers=headers)
    refund = await client.post(
        "/refunds",
        headers=headers,
        json={"payment_id": pid, "amount_minor": 1000},
    )
    assert refund.status_code == 201
    rid = refund.json()["id"]
    got = await client.get(f"/refunds/{rid}", headers=headers)
    assert got.status_code == 200
    listed = await client.get("/refunds", headers=headers)
    assert listed.status_code == 200


@pytest.mark.asyncio
async def test_payment_fail_and_get(client, merchant_bundle, customer):
    headers = merchant_bundle["api_headers"]
    create = await client.post(
        "/payments",
        headers=headers,
        json={"customer_id": customer["id"], "amount_minor": 5000, "currency": "INR"},
    )
    pid = create.json()["id"]
    failed = await client.post(f"/payments/{pid}/fail", headers=headers)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    got = await client.get(f"/payments/{pid}", headers=headers)
    assert got.status_code == 200


@pytest.mark.asyncio
async def test_validation_error_shape(client, merchant_bundle):
    headers = merchant_bundle["api_headers"]
    resp = await client.post("/customers", headers=headers, json={"email": "bad"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) >= {"code", "message", "details"}
