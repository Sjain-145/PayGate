from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.base import CRUDService
from app.deps import AuthContext, DbDep, require
from app.errors import AppError
from app.idempotency import IdempotencyDep
from app.models import Role, WebhookDelivery, WebhookEndpoint
from app.ratelimit import enforce_rate_limit
from app.schemas import (
    Page,
    WebhookDeliveryRead,
    WebhookEndpointCreate,
    WebhookEndpointRead,
    WebhookEndpointUpdate,
)
from app.webhooks import generate_webhook_secret

router = APIRouter(tags=["webhooks"])
endpoint_crud = CRUDService[
    WebhookEndpoint, WebhookEndpointCreate, WebhookEndpointUpdate, WebhookEndpoint
](WebhookEndpoint)
delivery_crud = CRUDService[
    WebhookDelivery, WebhookEndpointCreate, WebhookEndpointUpdate, WebhookDelivery
](WebhookDelivery)


@router.post("/webhook-endpoints", response_model=WebhookEndpointRead, status_code=201)
async def create_endpoint(
    data: WebhookEndpointCreate,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
    _: Annotated[AuthContext, Depends(enforce_rate_limit)],
    __: IdempotencyDep,
) -> WebhookEndpoint:
    if auth.merchant_id is None:
        raise AppError("forbidden", "Merchant context required", 403)
    secret = data.secret or generate_webhook_secret()
    payload = data.model_copy(update={"secret": secret})
    return await endpoint_crud.create(db, payload, merchant_id=auth.merchant_id)


@router.get("/webhook-endpoints", response_model=Page[WebhookEndpointRead])
async def list_endpoints(
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
    _: Annotated[AuthContext, Depends(enforce_rate_limit)],
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[WebhookEndpointRead]:
    filters = {}
    if auth.role != Role.admin:
        if auth.merchant_id is None:
            raise AppError("forbidden", "Merchant context required", 403)
        filters["merchant_id"] = auth.merchant_id
    items, next_cursor = await endpoint_crud.list(db, filters=filters, cursor=cursor, limit=limit)
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/webhook-endpoints/{endpoint_id}", response_model=WebhookEndpointRead)
async def get_endpoint(
    endpoint_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
) -> WebhookEndpoint:
    endpoint = await endpoint_crud.get_or_404(db, endpoint_id)
    if auth.role != Role.admin and endpoint.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Webhook endpoint not found", 404)
    return endpoint


@router.patch("/webhook-endpoints/{endpoint_id}", response_model=WebhookEndpointRead)
async def update_endpoint(
    endpoint_id: UUID,
    data: WebhookEndpointUpdate,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
) -> WebhookEndpoint:
    endpoint = await endpoint_crud.get_or_404(db, endpoint_id)
    if auth.role != Role.admin and endpoint.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Webhook endpoint not found", 404)
    return await endpoint_crud.update(db, endpoint_id, data)


@router.get("/webhook-deliveries", response_model=Page[WebhookDeliveryRead])
async def list_deliveries(
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[WebhookDeliveryRead]:
    filters = {}
    if auth.role != Role.admin:
        if auth.merchant_id is None:
            raise AppError("forbidden", "Merchant context required", 403)
        filters["merchant_id"] = auth.merchant_id
    items, next_cursor = await delivery_crud.list(db, filters=filters, cursor=cursor, limit=limit)
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/webhook-deliveries/{delivery_id}", response_model=WebhookDeliveryRead)
async def get_delivery(
    delivery_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
) -> WebhookDelivery:
    delivery = await delivery_crud.get_or_404(db, delivery_id)
    if auth.role != Role.admin and delivery.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Webhook delivery not found", 404)
    return delivery
