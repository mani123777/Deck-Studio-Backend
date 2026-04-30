from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.presentation import Presentation
from app.models.template import Template
from app.models.user import User
from app.models.theme import Theme
from app.schemas.presentation import (
    CreatePresentationRequest,
    PresentationDetail,
    PresentationListItem,
    SlideBackgroundSchema,
    SlideSchema,
    UpdatePresentationRequest,
)


def _slide_count(p: Presentation) -> int:
    return len(p.slides) if p.slides else 0


def _to_list_item(p: Presentation, template_name: str = "") -> PresentationListItem:
    count = _slide_count(p)
    first_slide_schemas = _slide_dicts_to_schemas(p.slides[:1]) if p.slides else []
    return PresentationListItem(
        id=str(p.id),
        title=p.title,
        description=p.description,
        template_id=str(p.template_id),
        template_name=template_name,
        theme_id=str(p.theme_id),
        is_preview=p.is_preview,
        total_slides=count,
        slide_count=count,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
        preview_slide=first_slide_schemas[0] if first_slide_schemas else None,
    )


def _slide_dicts_to_schemas(slides: list) -> list[SlideSchema]:
    result = []
    for s in (slides or []):
        blocks = []
        for b in s.get("blocks", []):
            blocks.append({
                "id": b.get("id", ""),
                "type": b.get("type", "text"),
                "content": b.get("content", ""),
                "position": b.get("position", {"x": 0, "y": 0, "w": 100, "h": 100}),
                "styling": b.get("styling", {}),
            })
        bg = s.get("background")
        result.append(SlideSchema(
            order=s.get("order", 0),
            type=s.get("type", "content"),
            background=SlideBackgroundSchema(**bg) if bg else None,
            blocks=blocks,
        ))
    return result


def _to_detail(p: Presentation, template_name: str = "") -> PresentationDetail:
    slides = _slide_dicts_to_schemas(p.slides)
    count = _slide_count(p)
    return PresentationDetail(
        id=str(p.id),
        title=p.title,
        description=p.description,
        template_id=str(p.template_id),
        template_name=template_name,
        theme_id=str(p.theme_id),
        is_preview=p.is_preview,
        total_slides=count,
        slide_count=count,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
        slides=slides,
        logo_url=p.logo_url or "",
    )


async def _get_template_name(db: AsyncSession, template_id: str) -> str:
    t = (await db.execute(select(Template).where(Template.id == template_id))).scalar_one_or_none()
    return t.name if t else ""


async def list_presentations(
    db: AsyncSession, user: User, is_preview: Optional[bool] = None
) -> list[PresentationListItem]:
    stmt = select(Presentation).where(Presentation.user_id == user.id)
    if is_preview is not None:
        stmt = stmt.where(Presentation.is_preview == is_preview)
    stmt = stmt.order_by(Presentation.updated_at.desc())
    items = (await db.execute(stmt)).scalars().all()

    # Batch-load template names
    template_ids = list({p.template_id for p in items})
    templates = (await db.execute(select(Template).where(Template.id.in_(template_ids)))).scalars().all()
    tmap = {t.id: t.name for t in templates}

    return [_to_list_item(p, tmap.get(p.template_id, "")) for p in items]


async def get_presentation(
    db: AsyncSession, user: User, presentation_id: str
) -> PresentationDetail:
    p = (
        await db.execute(select(Presentation).where(Presentation.id == presentation_id))
    ).scalar_one_or_none()
    if not p:
        raise NotFoundError(f"Presentation {presentation_id} not found")
    if p.user_id and str(p.user_id) != str(user.id) and user.role != "admin":
        raise ForbiddenError()
    tname = await _get_template_name(db, p.template_id)
    return _to_detail(p, tname)


async def update_presentation(
    db: AsyncSession, user: User, presentation_id: str, req: UpdatePresentationRequest
) -> PresentationDetail:
    p = (
        await db.execute(select(Presentation).where(Presentation.id == presentation_id))
    ).scalar_one_or_none()
    if not p:
        raise NotFoundError(f"Presentation {presentation_id} not found")
    if p.user_id and str(p.user_id) != str(user.id) and user.role != "admin":
        raise ForbiddenError()

    if req.title is not None:
        p.title = req.title
    if req.description is not None:
        p.description = req.description
    if req.logo_url is not None:
        p.logo_url = req.logo_url
    if req.theme_id is not None:
        p.theme_id = req.theme_id
    if req.slides is not None:
        p.slides = [
            {
                "order": s.order,
                "type": s.type,
                "background": s.background.model_dump() if s.background else None,
                "blocks": [
                    {
                        "id": b.id,
                        "type": b.type,
                        "content": b.content,
                        "position": b.position.model_dump(),
                        "styling": b.styling.model_dump(),
                    }
                    for b in s.blocks
                ],
            }
            for s in req.slides
        ]

    await db.commit()
    await db.refresh(p)
    tname = await _get_template_name(db, p.template_id)
    return _to_detail(p, tname)


async def create_presentation(
    db: AsyncSession, user: User, req: CreatePresentationRequest
) -> PresentationDetail:
    # Resolve template_id: use provided or fall back to first available template
    template_id = req.template_id
    if not template_id:
        first_template = (await db.execute(select(Template))).scalars().first()
        if not first_template:
            from app.core.exceptions import NotFoundError
            raise NotFoundError("No templates found in database")
        template_id = str(first_template.id)

    slides_data = [
        {
            "order": s.order,
            "type": s.type,
            "background": s.background.model_dump() if s.background else None,
            "blocks": [
                {
                    "id": b.id,
                    "type": b.type,
                    "content": b.content,
                    "position": b.position.model_dump(),
                    "styling": b.styling.model_dump(),
                }
                for b in s.blocks
            ],
        }
        for s in req.slides
    ]

    presentation = Presentation(
        user_id=str(user.id),
        template_id=template_id,
        theme_id=req.theme_id,
        title=req.title,
        description=req.description,
        logo_url=req.logo_url,
        slides=slides_data,
        is_preview=False,
    )
    db.add(presentation)
    await db.commit()
    await db.refresh(presentation)
    tname = await _get_template_name(db, template_id)
    return _to_detail(presentation, tname)


async def delete_presentation(db: AsyncSession, user: User, presentation_id: str) -> None:
    p = (
        await db.execute(select(Presentation).where(Presentation.id == presentation_id))
    ).scalar_one_or_none()
    if not p:
        raise NotFoundError(f"Presentation {presentation_id} not found")
    if p.user_id and str(p.user_id) != str(user.id) and user.role != "admin":
        raise ForbiddenError()
    await db.delete(p)
    await db.commit()
