from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import AuthError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import RegisterRequest, TokenResponse, UserPublic
from app.config import settings


async def register(db: AsyncSession, req: RegisterRequest) -> UserPublic:
    existing = (await db.execute(select(User).where(User.email == req.email))).scalar_one_or_none()
    if existing:
        raise ValidationError("Email is already registered")
    user = User(
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_to_public(user)


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        raise AuthError("Invalid email or password")
    if not user.is_active:
        raise AuthError("Account is deactivated")
    return user


async def issue_tokens(db: AsyncSession, user: User) -> TokenResponse:
    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    rt = RefreshToken(user_id=user.id, token=refresh, expires_at=expires_at)
    db.add(rt)
    await db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh)


async def rotate_refresh(db: AsyncSession, refresh_token_str: str) -> TokenResponse:
    payload = decode_token(refresh_token_str)
    if payload.get("type") != "refresh":
        raise AuthError("Invalid token type")

    rt = (
        await db.execute(select(RefreshToken).where(RefreshToken.token == refresh_token_str))
    ).scalar_one_or_none()
    if not rt or rt.revoked:
        raise AuthError("Refresh token is invalid or revoked")
    if rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise AuthError("Refresh token has expired")

    rt.revoked = True
    await db.commit()

    user = (await db.execute(select(User).where(User.id == rt.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise AuthError("User not found or inactive")

    return await issue_tokens(db, user)


async def revoke_refresh(db: AsyncSession, refresh_token_str: str) -> None:
    rt = (
        await db.execute(select(RefreshToken).where(RefreshToken.token == refresh_token_str))
    ).scalar_one_or_none()
    if rt:
        rt.revoked = True
        await db.commit()


def _user_to_public(user: User) -> UserPublic:
    return UserPublic(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )
