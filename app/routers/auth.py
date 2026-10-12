from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.deps import DbDep, require
from app.errors import AppError
from app.models import Role, User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    data: UserCreate,
    db: DbDep,
    _: Annotated[object, Depends(require(Role.admin))],
) -> User:
    exists = await db.execute(select(User).where(User.email == data.email))
    if exists.scalar_one_or_none():
        raise AppError("conflict", "Email already registered", 409)
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        merchant_id=data.merchant_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: DbDep) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise AppError("unauthorized", "Invalid credentials", 401)
    token = create_access_token(str(user.id), user.role.value, user.merchant_id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
async def me(
    db: DbDep,
    auth: Annotated[object, Depends(require(Role.admin, Role.merchant, Role.readonly))],
) -> User:
    from app.deps import AuthContext

    assert isinstance(auth, AuthContext)
    if auth.user_id is None:
        raise AppError("unauthorized", "User token required", 401)
    user = await db.get(User, auth.user_id)
    if user is None:
        raise AppError("not_found", "User not found", 404)
    return user
