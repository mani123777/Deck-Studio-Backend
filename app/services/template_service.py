from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.models.presentation import Presentation
from app.models.template import Template
from app.models.theme import Theme
from app.schemas.template import TemplateDetail, TemplateListItem, TemplateMetadataSchema


def _to_list_item(
    t: Template,
    preview_slide: Optional[dict] = None,
    theme: Optional[Theme] = None,
) -> TemplateListItem:
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
        preview_slide=preview_slide,
        theme=(
            {
                "id": str(theme.id),
                "name": theme.name,
                "colors": theme.colors,
                "fonts": theme.fonts,
            }
            if theme
            else None
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

    # Batch-load themes
    theme_ids = list({t.theme_id for t in templates})
    theme_rows = (
        await db.execute(select(Theme).where(Theme.id.in_(theme_ids)))
    ).scalars().all()
    theme_map = {str(th.id): th for th in theme_rows}

    # Batch-load cached preview presentations (first slide only is needed)
    template_ids = [str(t.id) for t in templates]
    preview_rows = (
        await db.execute(
            select(Presentation).where(
                Presentation.template_id.in_(template_ids),
                Presentation.is_preview == True,  # noqa: E712
            )
        )
    ).scalars().all()
    preview_map: dict[str, dict] = {}
    for p in preview_rows:
        slides = p.slides or []
        if slides:
            preview_map[str(p.template_id)] = slides[0]

    def _first_slide(t: Template) -> Optional[dict]:
        # Prefer the cached preview's first slide; fall back to the raw template
        # JSON's first slide so thumbnails render before any preview is generated.
        cached = preview_map.get(str(t.id))
        if cached:
            return cached
        raw = t.slides or []
        return raw[0] if raw else None

    return [
        _to_list_item(
            t,
            preview_slide=_first_slide(t),
            theme=theme_map.get(str(t.theme_id)),
        )
        for t in templates
    ]


async def get_template(db: AsyncSession, template_id: str) -> TemplateDetail:
    t = (await db.execute(select(Template).where(Template.id == template_id))).scalar_one_or_none()
    if not t:
        raise NotFoundError(f"Template {template_id} not found")
    return _to_detail(t)
