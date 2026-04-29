from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.presentation import (
    CreatePresentationRequest,
    PresentationDetail,
    PresentationListItem,
    UpdatePresentationRequest,
)
from app.services import presentation_service

router = APIRouter(prefix="/presentations", tags=["presentations"])


@router.get("", response_model=list[PresentationListItem])
async def list_presentations(
    is_preview: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PresentationListItem]:
    return await presentation_service.list_presentations(db, current_user, is_preview)


@router.post("", response_model=PresentationDetail, status_code=status.HTTP_201_CREATED)
async def create_presentation(
    req: CreatePresentationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PresentationDetail:
    return await presentation_service.create_presentation(db, current_user, req)


@router.get("/{presentation_id}", response_model=PresentationDetail)
async def get_presentation(
    presentation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PresentationDetail:
    return await presentation_service.get_presentation(db, current_user, presentation_id)


@router.patch("/{presentation_id}", response_model=PresentationDetail)
async def update_presentation(
    presentation_id: str,
    req: UpdatePresentationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PresentationDetail:
    return await presentation_service.update_presentation(db, current_user, presentation_id, req)


@router.delete("/{presentation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_presentation(
    presentation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await presentation_service.delete_presentation(db, current_user, presentation_id)
