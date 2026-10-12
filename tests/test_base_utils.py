from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.base import CRUDService, decode_cursor, encode_cursor
from app.errors import AppError
from app.fraud import score_payment
from app.models import Merchant
from app.schemas import MerchantCreate, MerchantUpdate


def test_cursor_roundtrip():
    now = datetime.now(UTC)
    item_id = uuid4()
    cursor = encode_cursor(now, item_id)
    decoded_t, decoded_id = decode_cursor(cursor)
    assert decoded_id == item_id
    assert decoded_t == now


def test_invalid_cursor():
    with pytest.raises(AppError) as exc:
        decode_cursor("%%%")
    assert exc.value.code == "invalid_cursor"


@pytest.mark.asyncio
async def test_crud_update_delete(db_session):
    svc = CRUDService[Merchant, MerchantCreate, MerchantUpdate, Merchant](Merchant)
    item = await svc.create(db_session, MerchantCreate(name="X", email="x@test.com"))
    updated = await svc.update(db_session, item.id, MerchantUpdate(name="Y"))
    assert updated.name == "Y"
    await svc.delete(db_session, item.id)
    with pytest.raises(AppError):
        await svc.get_or_404(db_session, item.id)


def test_score_without_model(monkeypatch):
    from app import fraud

    monkeypatch.setattr(fraud, "_model", None)
    monkeypatch.setattr(fraud, "load_model", lambda: None)
    score, flagged = score_payment(100, 12, "INR")
    assert score == 0.0
    assert flagged is False
