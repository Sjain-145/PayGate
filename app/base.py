import base64
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.errors import AppError

ModelT = TypeVar("ModelT", bound=DeclarativeBase)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)
ReadT = TypeVar("ReadT", bound=BaseModel)

settings = get_settings()


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    payload = {"t": created_at.isoformat(), "id": str(item_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["t"]), UUID(payload["id"])
    except Exception as exc:
        raise AppError("invalid_cursor", "Cursor is invalid", 400) from exc


def apply_filters(stmt: Select, model: type, filters: dict[str, Any]) -> Select:
    clauses = []
    for key, value in filters.items():
        if value is None:
            continue
        if key.endswith("__gte"):
            clauses.append(getattr(model, key[:-5]) >= value)
        elif key.endswith("__lte"):
            clauses.append(getattr(model, key[:-5]) <= value)
        elif key.endswith("__gt"):
            clauses.append(getattr(model, key[:-4]) > value)
        elif key.endswith("__lt"):
            clauses.append(getattr(model, key[:-4]) < value)
        elif hasattr(model, key):
            clauses.append(getattr(model, key) == value)
    return stmt.where(and_(*clauses)) if clauses else stmt


def paginate_stmt(
    stmt: Select,
    model: type,
    *,
    cursor: str | None,
    limit: int,
) -> Select:
    limit = min(max(limit, 1), settings.cursor_max_limit)
    if cursor:
        created_at, item_id = decode_cursor(cursor)
        stmt = stmt.where(
            (model.created_at < created_at)
            | ((model.created_at == created_at) & (model.id < item_id))
        )
    return stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)


class CRUDService(Generic[ModelT, CreateT, UpdateT, ReadT]):
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    async def get(self, db: AsyncSession, item_id: UUID) -> ModelT | None:
        return await db.get(self.model, item_id)

    async def get_or_404(self, db: AsyncSession, item_id: UUID) -> ModelT:
        item = await self.get(db, item_id)
        if item is None:
            raise AppError("not_found", f"{self.model.__name__} not found", 404)
        return item

    async def list(
        self,
        db: AsyncSession,
        *,
        filters: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[Sequence[ModelT], str | None]:
        limit = limit or settings.cursor_default_limit
        stmt = select(self.model)
        stmt = apply_filters(stmt, self.model, filters or {})
        stmt = paginate_stmt(stmt, self.model, cursor=cursor, limit=limit)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)
        return rows, next_cursor

    async def create(self, db: AsyncSession, data: CreateT, **extra: Any) -> ModelT:
        payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
        payload.update(extra)
        item = self.model(**payload)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def update(self, db: AsyncSession, item_id: UUID, data: UpdateT) -> ModelT:
        item = await self.get_or_404(db, item_id)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(item, key, value)
        await db.commit()
        await db.refresh(item)
        return item

    async def delete(self, db: AsyncSession, item_id: UUID) -> None:
        item = await self.get_or_404(db, item_id)
        await db.delete(item)
        await db.commit()
