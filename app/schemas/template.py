from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TemplateMetadataSchema(BaseModel):
    total_slides: int
    estimated_duration: int
    default_audience: str


class TemplateListItem(BaseModel):
    id: str
    name: str
    description: str
    category: str
    tags: list[str]
    thumbnail_url: str
    theme_id: str
    is_active: bool
    metadata: TemplateMetadataSchema
    preview_slide: Optional[dict] = None
    theme: Optional[dict] = None


class TemplateDetail(TemplateListItem):
    slides: list[dict]
    preview_presentation_id: Optional[str] = None


class TemplateFilter(BaseModel):
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: bool = True


class PreviewResponse(BaseModel):
    slides: list[dict]
    theme: dict
