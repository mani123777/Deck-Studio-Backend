from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.presentation import Presentation
from app.models.template import Template
from app.models.theme import Theme
from app.models.user import User
from app.schemas.template import PreviewResponse, TemplateDetail, TemplateListItem
from app.services import template_service

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateListItem])
async def list_templates(
    category: Optional[str] = Query(None),
    tags: Optional[list[str]] = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateListItem]:
    return await template_service.list_templates(db, category=category, tags=tags)


@router.get("/{template_id}", response_model=TemplateDetail)
async def get_template(
    template_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateDetail:
    return await template_service.get_template(db, template_id)


@router.get("/{template_id}/preview", response_model=PreviewResponse)
async def get_template_preview(
    template_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse:
    """
    Return a Gamma-style rendered preview for a template.
    If a cached preview presentation already exists, return it immediately.
    Otherwise, generate one via the full pipeline and cache it.
    """
    # Load template
    template = (
        await db.execute(select(Template).where(Template.id == template_id))
    ).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    # Load theme
    theme = (
        await db.execute(select(Theme).where(Theme.id == template.theme_id))
    ).scalar_one_or_none()
    if not theme:
        raise HTTPException(status_code=404, detail=f"Theme {template.theme_id} not found")

    # Check for existing cached preview
    existing = (
        await db.execute(
            select(Presentation).where(
                Presentation.template_id == template_id,
                Presentation.is_preview == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()

    if existing:
        slides = existing.slides or []
    else:
        # Generate preview via the Gamma pipeline
        from app.agents.generation.preview_generator_agent import PreviewGeneratorAgent

        agent = PreviewGeneratorAgent()
        try:
            preview = await agent.run(template, theme)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Preview generation failed: {exc}") from exc
        slides = preview.slides or []

    theme_dict = {
        "id": str(theme.id),
        "name": theme.name,
        "colors": theme.colors,
        "fonts": theme.fonts,
    }

    return PreviewResponse(slides=slides, theme=theme_dict)
