import asyncio
import json
import random
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.security import hmac_sign

settings = get_settings()

celery_app = Celery(
    "paygate",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")


def backoff_delay(attempt: int) -> float:
    base = settings.webhook_base_delay_seconds * (2 ** max(attempt - 1, 0))
    delay = min(base, settings.webhook_max_delay_seconds)
    jitter = random.uniform(0, delay * 0.2)
    return delay + jitter


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


async def enqueue_event(merchant_id: UUID, event_type: str, payload: dict[str, Any]) -> list[UUID]:
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.merchant_id == merchant_id,
                WebhookEndpoint.is_active.is_(True),
            )
        )
        endpoints = list(result.scalars().all())
        delivery_ids: list[UUID] = []
        for endpoint in endpoints:
            events = endpoint.events or ["*"]
            if "*" not in events and event_type not in events:
                continue
            delivery = WebhookDelivery(
                endpoint_id=endpoint.id,
                merchant_id=merchant_id,
                event_type=event_type,
                payload=payload,
                status=DeliveryStatus.pending,
                attempt_count=0,
                attempts=[],
            )
            db.add(delivery)
            await db.flush()
            delivery_ids.append(delivery.id)
        await db.commit()
    for delivery_id in delivery_ids:
        if settings.environment == "test":
            await attempt_delivery(delivery_id)
        else:
            try:
                deliver_webhook.delay(str(delivery_id))
            except Exception:
                await attempt_delivery(delivery_id)
    return delivery_ids


async def attempt_delivery(delivery_id: UUID) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id)
            .options(selectinload(WebhookDelivery.endpoint))
        )
        delivery = result.scalar_one_or_none()
        if delivery is None or delivery.status != DeliveryStatus.pending:
            return
        endpoint = delivery.endpoint
        body = json.dumps(
            {
                "id": str(delivery.id),
                "type": delivery.event_type,
                "data": delivery.payload,
                "created_at": datetime.now(UTC).isoformat(),
            },
            default=str,
        ).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = hmac_sign(endpoint.secret, timestamp, body)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "X-Event-Type": delivery.event_type,
        }
        status_code = None
        error = None
        success = False
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
                resp = await client.post(endpoint.url, content=body, headers=headers)
                status_code = resp.status_code
                success = 200 <= resp.status_code < 300
                if not success:
                    error = resp.text[:500]
        except Exception as exc:
            error = str(exc)

        delivery.attempt_count += 1
        attempts = list(delivery.attempts or [])
        attempts.append(
            {
                "attempt": delivery.attempt_count,
                "at": datetime.now(UTC).isoformat(),
                "status_code": status_code,
                "error": error,
            }
        )
        delivery.attempts = attempts
        delivery.last_status_code = status_code
        delivery.last_error = error

        should_retry = False
        retry_delay = 0.0
        if success:
            delivery.status = DeliveryStatus.success
            delivery.next_attempt_at = None
        elif delivery.attempt_count >= settings.webhook_max_attempts:
            delivery.status = DeliveryStatus.failed
            delivery.next_attempt_at = None
        else:
            retry_delay = backoff_delay(delivery.attempt_count)
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=retry_delay)
            should_retry = True
        await db.commit()

    if should_retry:
        if settings.environment == "test":
            await attempt_delivery(delivery_id)
        else:
            deliver_webhook.apply_async(args=[str(delivery_id)], countdown=retry_delay)


@celery_app.task(name="paygate.deliver_webhook")
def deliver_webhook(delivery_id: str) -> None:
    asyncio.run(attempt_delivery(UUID(delivery_id)))
