import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, Merchant, Role, User
from app.security import generate_api_key, hash_password


async def seed() -> None:
    async with SessionLocal() as db:
        existing = await db.execute(select(Merchant).where(Merchant.email == "demo@paygate.test"))
        merchant = existing.scalar_one_or_none()
        if merchant is None:
            merchant = Merchant(name="Demo Merchant", email="demo@paygate.test")
            db.add(merchant)
            await db.flush()

        user_result = await db.execute(select(User).where(User.email == "admin@paygate.test"))
        if user_result.scalar_one_or_none() is None:
            db.add(
                User(
                    email="admin@paygate.test",
                    password_hash=hash_password("adminpass123"),
                    role=Role.admin,
                )
            )

        merchant_user = await db.execute(select(User).where(User.email == "demo@paygate.test"))
        if merchant_user.scalar_one_or_none() is None:
            db.add(
                User(
                    email="demo@paygate.test",
                    password_hash=hash_password("demopass123"),
                    role=Role.merchant,
                    merchant_id=merchant.id,
                )
            )

        key_result = await db.execute(
            select(ApiKey).where(ApiKey.merchant_id == merchant.id, ApiKey.name == "demo")
        )
        if key_result.scalar_one_or_none() is None:
            full, prefix, key_hash = generate_api_key()
            db.add(
                ApiKey(
                    merchant_id=merchant.id,
                    name="demo",
                    key_prefix=prefix,
                    key_hash=key_hash,
                )
            )
            await db.commit()
            print(f"DEMO_API_KEY={full}")
            print(f"DEMO_MERCHANT_ID={merchant.id}")
        else:
            await db.commit()
            print("Demo data already present")


if __name__ == "__main__":
    asyncio.run(seed())
