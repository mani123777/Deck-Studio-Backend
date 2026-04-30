from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PositionSchema(BaseModel):
    x: float
    y: float
    w: float
    h: float


class StylingSchema(BaseModel):
    font_family: str = ""
    font_size: int = 16
    font_weight: int = 400
    color: str = "#000000"
    background_color: str = "transparent"
    text_align: str = "left"


class BlockSchema(BaseModel):
    id: str
    type: str
    content: str = ""
    position: PositionSchema
    styling: StylingSchema = StylingSchema()


class SlideBackgroundSchema(BaseModel):
    type: str = "color"
    value: str = "#ffffff"


class SlideSchema(BaseModel):
    order: int
    type: str
    background: Optional[SlideBackgroundSchema] = None
    blocks: list[BlockSchema] = []


class PresentationListItem(BaseModel):
    id: str
    title: str
    description: str
    template_id: str
    template_name: str
    theme_id: str
    is_preview: bool
    total_slides: int
    slide_count: int
    created_at: str
    updated_at: str = ""
    preview_slide: Optional[SlideSchema] = None


class PresentationDetail(PresentationListItem):
    slides: list[SlideSchema]
    logo_url: str


class UpdatePresentationRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    theme_id: Optional[str] = None
    slides: Optional[list[SlideSchema]] = None


class CreatePresentationRequest(BaseModel):
    title: str
    description: str = ""
    slides: list[SlideSchema]
    theme_id: str
    template_id: str = ""
    logo_url: str = ""
