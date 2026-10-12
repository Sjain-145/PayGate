from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.base import CRUDService
from app.deps import AuthContext, DbDep, require
from app.errors import AppError
from app.models import ApiKey, Customer, Merchant, Role
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    MerchantCreate,
    MerchantRead,
    MerchantUpdate,
    Page,
)
from app.security import generate_api_key

router = APIRouter(tags=["merchants"])
merchant_service = CRUDService[Merchant, MerchantCreate, MerchantUpdate, Merchant](Merchant)
customer_service = CRUDService[Customer, CustomerCreate, CustomerUpdate, Customer](Customer)


@router.post("/merchants", response_model=MerchantRead, status_code=201)
async def create_merchant(
    data: MerchantCreate,
    db: DbDep,
    _: Annotated[AuthContext, Depends(require(Role.admin))],
) -> Merchant:
    return await merchant_service.create(db, data)


@router.get("/merchants", response_model=Page[MerchantRead])
async def list_merchants(
    db: DbDep,
    _: Annotated[AuthContext, Depends(require(Role.admin))],
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[MerchantRead]:
    items, next_cursor = await merchant_service.list(db, cursor=cursor, limit=limit)
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/merchants/{merchant_id}", response_model=MerchantRead)
async def get_merchant(
    merchant_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
) -> Merchant:
    if auth.role != Role.admin and auth.merchant_id != merchant_id:
        raise AppError("forbidden", "Insufficient permissions", 403)
    return await merchant_service.get_or_404(db, merchant_id)


@router.patch("/merchants/{merchant_id}", response_model=MerchantRead)
async def update_merchant(
    merchant_id: UUID,
    data: MerchantUpdate,
    db: DbDep,
    _: Annotated[AuthContext, Depends(require(Role.admin))],
) -> Merchant:
    return await merchant_service.update(db, merchant_id, data)


@router.post("/merchants/{merchant_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    merchant_id: UUID,
    data: ApiKeyCreate,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
) -> ApiKeyCreated:
    if auth.role != Role.admin and auth.merchant_id != merchant_id:
        raise AppError("forbidden", "Insufficient permissions", 403)
    await merchant_service.get_or_404(db, merchant_id)
    full, prefix, key_hash = generate_api_key()
    api_key = ApiKey(merchant_id=merchant_id, name=data.name, key_prefix=prefix, key_hash=key_hash)
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return ApiKeyCreated(
        id=api_key.id,
        merchant_id=api_key.merchant_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        api_key=full,
    )


@router.get("/merchants/{merchant_id}/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    merchant_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
) -> list[ApiKey]:
    if auth.role != Role.admin and auth.merchant_id != merchant_id:
        raise AppError("forbidden", "Insufficient permissions", 403)
    items, _ = await CRUDService(ApiKey).list(db, filters={"merchant_id": merchant_id}, limit=100)
    return list(items)


@router.post("/customers", response_model=CustomerRead, status_code=201)
async def create_customer(
    data: CustomerCreate,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant))],
) -> Customer:
    if auth.merchant_id is None:
        raise AppError("forbidden", "Merchant context required", 403)
    return await customer_service.create(db, data, merchant_id=auth.merchant_id)


@router.get("/customers", response_model=Page[CustomerRead])
async def list_customers(
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[CustomerRead]:
    filters = {"merchant_id": auth.merchant_id} if auth.role != Role.admin else {}
    if auth.role == Role.admin:
        pass
    elif auth.merchant_id is None:
        raise AppError("forbidden", "Merchant context required", 403)
    items, next_cursor = await customer_service.list(
        db, filters=filters, cursor=cursor, limit=limit
    )
    return Page(items=list(items), next_cursor=next_cursor)


@router.get("/customers/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: UUID,
    db: DbDep,
    auth: Annotated[AuthContext, Depends(require(Role.admin, Role.merchant, Role.readonly))],
) -> Customer:
    customer = await customer_service.get_or_404(db, customer_id)
    if auth.role != Role.admin and customer.merchant_id != auth.merchant_id:
        raise AppError("not_found", "Customer not found", 404)
    return customer
