import os

os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://paygate:paygate@localhost:5433/paygate_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/14"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/13"
os.environ["RATE_LIMIT_REQUESTS"] = "1000"
os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"
os.environ["WEBHOOK_MAX_ATTEMPTS"] = "3"
os.environ["WEBHOOK_BASE_DELAY_SECONDS"] = "0.01"
os.environ["FRAUD_THRESHOLD"] = "0.5"
os.environ["FRAUD_MODEL_PATH"] = "artifacts/fraud_model.joblib"
os.environ["IDEMPOTENCY_TTL_SECONDS"] = "3600"

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import Base, get_db
from app.fraud import load_model, train_and_save
from app.models import ApiKey, Merchant, Role, User
from app.security import create_access_token, generate_api_key, hash_password

get_settings.cache_clear()
settings = get_settings()
train_and_save(settings.fraud_model_path)
load_model()


async def _ensure_test_db() -> None:
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        exists = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname='paygate_test'"))
        if exists.scalar() is None:
            await conn.execute(text("CREATE DATABASE paygate_test"))
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_engine():
    await _ensure_test_db()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    import app.db as db_module
    import app.webhooks as webhooks_module

    db_module.engine = engine
    db_module.SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    webhooks_module.SessionLocal = db_module.SessionLocal
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


@pytest.fixture
def disable_webhooks():
    with patch("app.routers.payments.enqueue_event", new_callable=AsyncMock) as p1:
        with patch("app.routers.refunds.enqueue_event", new_callable=AsyncMock) as p2:
            yield p1, p2


@pytest_asyncio.fixture
async def client(db_engine, disable_webhooks) -> AsyncIterator[AsyncClient]:
    from app.main import app

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.flushdb()
    app.state.redis = redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await redis.aclose()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_with_webhooks(db_engine) -> AsyncIterator[AsyncClient]:
    from app.main import app

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.flushdb()
    app.state.redis = redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await redis.aclose()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def merchant_bundle(db_session: AsyncSession):
    merchant = Merchant(name="Test Merchant", email="merchant@test.com")
    db_session.add(merchant)
    await db_session.flush()

    admin = User(
        email="admin@test.com",
        password_hash=hash_password("adminpass123"),
        role=Role.admin,
    )
    merchant_user = User(
        email="merchant@test.com",
        password_hash=hash_password("merchantpass"),
        role=Role.merchant,
        merchant_id=merchant.id,
    )
    readonly = User(
        email="readonly@test.com",
        password_hash=hash_password("readonlypass"),
        role=Role.readonly,
        merchant_id=merchant.id,
    )
    db_session.add_all([admin, merchant_user, readonly])
    full, prefix, key_hash = generate_api_key()
    api_key = ApiKey(merchant_id=merchant.id, name="test", key_prefix=prefix, key_hash=key_hash)
    db_session.add(api_key)
    await db_session.commit()

    return {
        "merchant": merchant,
        "api_key": full,
        "api_headers": {"Authorization": f"Bearer {full}"},
        "admin_headers": {
            "Authorization": f"Bearer {create_access_token(str(admin.id), Role.admin.value)}"
        },
        "merchant_headers": {
            "Authorization": (
                f"Bearer {create_access_token(str(merchant_user.id), Role.merchant.value, merchant.id)}"
            )
        },
        "readonly_headers": {
            "Authorization": (
                f"Bearer {create_access_token(str(readonly.id), Role.readonly.value, merchant.id)}"
            )
        },
    }


@pytest_asyncio.fixture
async def customer(client: AsyncClient, merchant_bundle):
    resp = await client.post(
        "/customers",
        headers=merchant_bundle["api_headers"],
        json={"email": "cust@test.com", "name": "Cust"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
