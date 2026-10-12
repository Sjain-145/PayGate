from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.base import CRUDService
from app.deps import AuthContext, DbDep, require
from app.errors import AppError
from app.idempotency import IdempotencyDep
from app.models import Payment, PaymentStatus, Refund, Role
from app.ratelimit import enforce_rate_limit
from app.schemas import Page, RefundCreate, RefundRead
from app.webhooks import enqueue_event

router = APIRouter(prefix="/refunds", tags=["refunds"])
refund_crud = CRUDService[Refund, RefundCreate, RefundCreate, Refund](Refund)


@router.post("", response_model=RefundRead, status_code=201)
async def create_refund(
    data: RefundCreate,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
    _: Annotated[AuthContext, Depends(enforce_rate_limit)],
    __: IdempotencyDep,
) -> Refund:
    if auth.merchant_id is None and auth.role != Role.admin:
        raise AppError("forbidden", "Merchant context required", 403)

    result = await db.execute(
        select(Payment).where(Payment.id == data.payment_id).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise AppError("not_found", "Payment not found", 404)
    if auth.role != Role.admin and payment.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Payment not found", 404)
    if payment.status != PaymentStatus.captured:
        raise AppError(
            "invalid_state",
            "Refunds require a captured payment",
            409,
            details={"status": payment.status.value},
        )
    refunded = await db.execute(select(Refund.amount_minor).where(Refund.payment_id == payment.id))
    total_refunded = sum(refunded.scalars().all())
    if total_refunded + data.amount_minor > payment.amount_minor:
        raise AppError(
            "refund_exceeds_capture",
            "Refund amount exceeds captured amount",
            409,
            details={
                "captured": payment.amount_minor,
                "already_refunded": total_refunded,
                "requested": data.amount_minor,
            },
        )
    refund = Refund(
        payment_id=payment.id,
        merchant_id=payment.merchant_id,
        amount_minor=data.amount_minor,
        currency=payment.currency,
        reason=data.reason,
        status="succeeded",
    )
    db.add(refund)
    await db.commit()
    await db.refresh(refund)
    await enqueue_event(
        payment.merchant_id,
        "refund.created",
        {
            "refund_id": str(refund.id),
            "payment_id": str(payment.id),
            "amount_minor": refund.amount_minor,
            "currency": refund.currency,
        },
    )
    return refund


@router.get("", response_model=Page[RefundRead])
async def list_refunds(
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
    _: Annotated[AuthContext, Depends(enforce_rate_limit)],
    cursor: str | None = None,
    limit: int | None = None,
    payment_id: UUID | None = None,
) -> Page[RefundRead]:
    filters: dict = {}
    if auth.role != Role.admin:
        if auth.merchant_id is None:
            raise AppError("forbidden", "Merchant context required", 403)
        filters["merchant_id"] = auth.merchant_id
    if payment_id:
        filters["payment_id"] = payment_id
    items, next_cursor = await refund_crud.list(db, filters=filters, cursor=cursor, limit=limit)
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/{refund_id}", response_model=RefundRead)
async def get_refund(
    refund_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
    _: Annotated[AuthContext, Depends(enforce_rate_limit)],
) -> Refund:
    refund = await refund_crud.get_or_404(db, refund_id)
    if auth.role != Role.admin and refund.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Refund not found", 404)
    return refund
