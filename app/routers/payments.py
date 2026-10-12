from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.base import CRUDService
from app.deps import AuthContext, DbDep, require
from app.errors import AppError
from app.fraud import score_payment
from app.idempotency import IdempotencyDep
from app.models import Customer, Payment, PaymentStatus, Role
from app.ratelimit import enforce_rate_limit
from app.schemas import Page, PaymentCreate, PaymentRead
from app.webhooks import enqueue_event

router = APIRouter(prefix="/payments", tags=["payments"])
payment_crud = CRUDService[Payment, PaymentCreate, PaymentCreate, Payment](Payment)

TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.created: {
        PaymentStatus.authorized,
        PaymentStatus.cancelled,
        PaymentStatus.failed,
    },
    PaymentStatus.authorized: {
        PaymentStatus.captured,
        PaymentStatus.cancelled,
        PaymentStatus.failed,
    },
    PaymentStatus.captured: set(),
    PaymentStatus.cancelled: set(),
    PaymentStatus.failed: set(),
}


def apply_transition(payment: Payment, new_status: PaymentStatus) -> Payment:
    allowed = TRANSITIONS.get(payment.status, set())
    if new_status not in allowed:
        raise AppError(
            "invalid_transition",
            f"Cannot transition from {payment.status.value} to {new_status.value}",
            409,
            details={"from": payment.status.value, "to": new_status.value},
        )
    payment.status = new_status
    return payment


async def _merchant_payment(db, payment_id: UUID, auth: AuthContext) -> Payment:
    payment = await payment_crud.get_or_404(db, payment_id)
    if auth.role != Role.admin and payment.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Payment not found", 404)
    return payment


WriteAuth = Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))]
ReadAuth = Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))]
RateLimited = Annotated[AuthContext, Depends(enforce_rate_limit)]


@router.post("", response_model=PaymentRead, status_code=201)
async def create_payment(
    data: PaymentCreate,
    db: DbDep,
    auth: WriteAuth,
    _: RateLimited,
    __: IdempotencyDep,
) -> Payment:
    if auth.merchant_id is None:
        raise AppError("forbidden", "Merchant context required", 403)
    customer = await db.get(Customer, data.customer_id)
    if customer is None or customer.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Customer not found", 404)
    risk_score, fraud_flagged = score_payment(
        data.amount_minor, datetime.now(UTC).hour, data.currency
    )
    payment = await payment_crud.create(
        db,
        data,
        merchant_id=auth.merchant_id,
        status=PaymentStatus.created,
        risk_score=risk_score,
        fraud_flagged=fraud_flagged,
    )
    await enqueue_event(
        auth.merchant_id,
        "payment.created",
        {
            "payment_id": str(payment.id),
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "status": payment.status.value,
            "risk_score": payment.risk_score,
            "fraud_flagged": payment.fraud_flagged,
        },
    )
    return payment


@router.get("", response_model=Page[PaymentRead])
async def list_payments(
    db: DbDep,
    auth: ReadAuth,
    _: RateLimited,
    cursor: str | None = None,
    limit: int | None = None,
    status: PaymentStatus | None = None,
    amount_minor__gte: int | None = None,
    amount_minor__lte: int | None = None,
    created_at__gte: datetime | None = None,
    created_at__lte: datetime | None = None,
) -> Page[PaymentRead]:
    filters: dict = {}
    if auth.role != Role.admin:
        if auth.merchant_id is None:
            raise AppError("forbidden", "Merchant context required", 403)
        filters["merchant_id"] = auth.merchant_id
    filters.update(
        {
            "status": status,
            "amount_minor__gte": amount_minor__gte,
            "amount_minor__lte": amount_minor__lte,
            "created_at__gte": created_at__gte,
            "created_at__lte": created_at__lte,
        }
    )
    items, next_cursor = await payment_crud.list(db, filters=filters, cursor=cursor, limit=limit)
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(payment_id: UUID, db: DbDep, auth: ReadAuth, _: RateLimited) -> Payment:
    return await _merchant_payment(db, payment_id, auth)


async def _set_status(
    db, payment_id: UUID, auth: AuthContext, new_status: PaymentStatus
) -> Payment:
    payment = await _merchant_payment(db, payment_id, auth)
    apply_transition(payment, new_status)
    await db.commit()
    await db.refresh(payment)
    await enqueue_event(
        payment.merchant_id,
        f"payment.{new_status.value}",
        {
            "payment_id": str(payment.id),
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "status": payment.status.value,
        },
    )
    return payment


@router.post("/{payment_id}/authorize", response_model=PaymentRead)
async def authorize_payment(
    payment_id: UUID, db: DbDep, auth: WriteAuth, _: RateLimited, __: IdempotencyDep
) -> Payment:
    return await _set_status(db, payment_id, auth, PaymentStatus.authorized)


@router.post("/{payment_id}/capture", response_model=PaymentRead)
async def capture_payment(
    payment_id: UUID, db: DbDep, auth: WriteAuth, _: RateLimited, __: IdempotencyDep
) -> Payment:
    return await _set_status(db, payment_id, auth, PaymentStatus.captured)


@router.post("/{payment_id}/cancel", response_model=PaymentRead)
async def cancel_payment(
    payment_id: UUID, db: DbDep, auth: WriteAuth, _: RateLimited, __: IdempotencyDep
) -> Payment:
    return await _set_status(db, payment_id, auth, PaymentStatus.cancelled)


@router.post("/{payment_id}/fail", response_model=PaymentRead)
async def fail_payment(
    payment_id: UUID, db: DbDep, auth: WriteAuth, _: RateLimited, __: IdempotencyDep
) -> Payment:
    return await _set_status(db, payment_id, auth, PaymentStatus.failed)
