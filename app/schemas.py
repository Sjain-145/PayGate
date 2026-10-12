from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import DeliveryStatus, PaymentStatus, Role

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class UserBase(BaseModel):
    email: EmailStr
    role: Role = Role.merchant


class UserCreate(UserBase):
    password: str = Field(min_length=8)
    merchant_id: UUID | None = None


class UserRead(UserBase, ORMModel):
    id: UUID
    merchant_id: UUID | None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MerchantBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr


class MerchantCreate(MerchantBase):
    pass


class MerchantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class MerchantRead(MerchantBase, ORMModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "Acme Payments",
                    "email": "ops@acme.test",
                    "is_active": True,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        },
    )

    id: UUID
    is_active: bool
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ApiKeyRead(ORMModel):
    id: UUID
    merchant_id: UUID
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    api_key: str = Field(
        ...,
        description="Shown once. Store securely.",
        examples=["pg_live_example_key_value"],
    )


class CustomerBase(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class CustomerRead(CustomerBase, ORMModel):
    id: UUID
    merchant_id: UUID
    created_at: datetime


class PaymentBase(BaseModel):
    amount_minor: int = Field(gt=0, examples=[10000])
    currency: str = Field(default="INR", min_length=3, max_length=3, examples=["INR"])
    description: str | None = Field(default=None, max_length=512)
    metadata_json: dict | None = None


class PaymentCreate(PaymentBase):
    customer_id: UUID
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "customer_id": "22222222-2222-2222-2222-222222222222",
                    "amount_minor": 10000,
                    "currency": "INR",
                    "description": "Order #1001",
                }
            ]
        }
    )


class PaymentUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=512)
    metadata_json: dict | None = None


class PaymentRead(PaymentBase, ORMModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "merchant_id": "11111111-1111-1111-1111-111111111111",
                    "customer_id": "22222222-2222-2222-2222-222222222222",
                    "amount_minor": 10000,
                    "currency": "INR",
                    "status": "created",
                    "description": "Order #1001",
                    "risk_score": 0.12,
                    "fraud_flagged": False,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        },
    )

    id: UUID
    merchant_id: UUID
    customer_id: UUID
    status: PaymentStatus
    risk_score: float
    fraud_flagged: bool
    created_at: datetime
    updated_at: datetime


class RefundBase(BaseModel):
    amount_minor: int = Field(gt=0, examples=[2500])
    reason: str | None = Field(default=None, max_length=512)


class RefundCreate(RefundBase):
    payment_id: UUID


class RefundRead(RefundBase, ORMModel):
    id: UUID
    payment_id: UUID
    merchant_id: UUID
    currency: str
    status: str
    created_at: datetime


class WebhookEndpointBase(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(default_factory=lambda: ["*"])


class WebhookEndpointCreate(WebhookEndpointBase):
    secret: str | None = Field(default=None, min_length=8, max_length=255)


class WebhookEndpointUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    is_active: bool | None = None
    events: list[str] | None = None


class WebhookEndpointRead(WebhookEndpointBase, ORMModel):
    id: UUID
    merchant_id: UUID
    is_active: bool
    created_at: datetime


class WebhookDeliveryRead(ORMModel):
    id: UUID
    endpoint_id: UUID
    merchant_id: UUID
    event_type: str
    payload: dict
    status: DeliveryStatus
    attempt_count: int
    last_status_code: int | None
    last_error: str | None
    attempts: list
    created_at: datetime
