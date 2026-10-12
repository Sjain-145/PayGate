import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers_key", "method", "path", "expected"),
    [
        ("admin_headers", "GET", "/merchants", 200),
        ("merchant_headers", "GET", "/merchants", 403),
        ("readonly_headers", "POST", "/payments", 403),
        ("api_headers", "GET", "/payments", 200),
        ("readonly_headers", "GET", "/payments", 200),
    ],
)
async def test_rbac_matrix(client, merchant_bundle, customer, headers_key, method, path, expected):
    headers = merchant_bundle[headers_key]
    kwargs = {"headers": headers}
    if method == "POST" and path == "/payments":
        kwargs["json"] = {
            "customer_id": customer["id"],
            "amount_minor": 1000,
            "currency": "INR",
        }
    resp = await client.request(method, path, **kwargs)
    assert resp.status_code == expected


@pytest.mark.asyncio
async def test_login_and_me(client, merchant_bundle):
    resp = await client.post(
        "/auth/login", json={"email": "admin@test.com", "password": "adminpass123"}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@test.com"


@pytest.mark.asyncio
async def test_invalid_api_key(client):
    resp = await client.get("/payments", headers={"Authorization": "Bearer pg_live_invalid"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"
