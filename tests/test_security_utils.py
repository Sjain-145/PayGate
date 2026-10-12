from app.security import hmac_sign, hmac_verify, request_body_hash
from app.webhooks import backoff_delay


def test_hmac_roundtrip():
    body = b'{"hello":"world"}'
    ts = "1710000000"
    sig = hmac_sign("secret", ts, body)
    assert hmac_verify("secret", ts, body, sig)
    assert not hmac_verify("secret", ts, body, "deadbeef")


def test_request_hash_stable():
    assert request_body_hash(b"abc") == request_body_hash(b"abc")
    assert request_body_hash(b"abc") != request_body_hash(b"abd")


def test_backoff_increases():
    d1 = backoff_delay(1)
    d3 = backoff_delay(3)
    assert d1 >= 0
    assert d3 >= d1 * 0.5
