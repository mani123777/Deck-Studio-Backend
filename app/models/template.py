from __future__ import annotations

from sqlalchemy import String, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class Template(TimestampedModel):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    thumbnail_url: Mapped[str] = mapped_column(String(500), default="")
    theme_id: Mapped[str] = mapped_column(String(36), ForeignKey("themes.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False
    )  # {total_slides, estimated_duration, default_audience}
    slides: Mapped[list] = mapped_column(JSON, default=list)
    preview_pptx_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
