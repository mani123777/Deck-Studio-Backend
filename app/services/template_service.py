from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.models.template import Template
from app.schemas.template import TemplateDetail, TemplateListItem, TemplateMetadataSchema


def _to_list_item(t: Template) -> TemplateListItem:
    meta = t.metadata_json or {}
    return TemplateListItem(
        id=str(t.id),
        name=t.name,
        description=t.description,
        category=t.category,
        tags=t.tags or [],
        thumbnail_url=t.thumbnail_url or "",
        theme_id=str(t.theme_id),
        is_active=t.is_active,
        metadata=TemplateMetadataSchema(
            total_slides=meta.get("total_slides", 0),
            estimated_duration=meta.get("estimated_duration", 0),
            default_audience=meta.get("default_audience", ""),
        ),
    )


def _to_detail(t: Template) -> TemplateDetail:
    meta = t.metadata_json or {}
    return TemplateDetail(
        id=str(t.id),
        name=t.name,
        description=t.description,
        category=t.category,
        tags=t.tags or [],
        thumbnail_url=t.thumbnail_url or "",
        theme_id=str(t.theme_id),
        is_active=t.is_active,
        metadata=TemplateMetadataSchema(
            total_slides=meta.get("total_slides", 0),
            estimated_duration=meta.get("estimated_duration", 0),
            default_audience=meta.get("default_audience", ""),
        ),
        slides=t.slides or [],
        preview_presentation_id=t.preview_pptx_path or None,
    )


async def list_templates(
    db: AsyncSession,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    is_active: bool = True,
) -> list[TemplateListItem]:
    stmt = select(Template).where(Template.is_active == is_active)
    if category:
        stmt = stmt.where(Template.category == category)
    result = await db.execute(stmt)
    templates = result.scalars().all()

    # Filter by tags in Python (JSON column tag filtering)
    if tags:
        templates = [t for t in templates if all(tag in (t.tags or []) for tag in tags)]

    return [_to_list_item(t) for t in templates]


async def get_template(db: AsyncSession, template_id: str) -> TemplateDetail:
    t = (await db.execute(select(Template).where(Template.id == template_id))).scalar_one_or_none()
    if not t:
        raise NotFoundError(f"Template {template_id} not found")
    return _to_detail(t)
