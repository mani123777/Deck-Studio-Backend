from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gemini_client
from app.ai.prompt_templates import COMBINED_GENERATION_PROMPT, render
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.extractors.extractor_factory import extract_content
from app.models.template import Template
from app.models.theme import Theme
from app.models.user import User
from app.schemas.template import PreviewResponse
from app.utils.logger import get_logger

router = APIRouter(prefix="/generate", tags=["generation"])
logger = get_logger(__name__)


async def _extract_file_text(file: UploadFile) -> str:
    """Save upload to temp file and extract text. Only PDF and DOCX are accepted."""
    suffix = Path(file.filename or "upload.txt").suffix.lower() or ".txt"
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        return extract_content(Path(tmp_path))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/sync", response_model=PreviewResponse)
async def generate_sync(
    prompt: str = Form(...),
    slide_count: int = Form(10),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse:
    """
    Synchronous generation: returns {slides, theme} in one request.
    Single Gemini API call — analysis + slide content combined.
    """
    from app.agents.generation.preview_generator_agent import _build_outline
    from app.agents.generation.slide_generator_agent import SlideGeneratorAgent
    from app.agents.generation.template_mapper_agent import TemplateMappingResult

    slide_count = max(5, min(20, slide_count))

    # Extract file text if provided
    content = prompt
    if file and file.filename:
        try:
            file_text = await _extract_file_text(file)
            if len(file_text) > 50_000:
                file_text = file_text[:50_000] + "\n...[content truncated]"
            content = f"{prompt}\n\n{file_text}" if prompt else file_text
        except Exception as exc:
            logger.warning(f"File extraction failed, using prompt only: {exc}")

    # Single Gemini call — analyze content + generate all slide content
    combined_prompt = render(
        COMBINED_GENERATION_PROMPT,
        prompt=prompt,
        content=content,
        slide_count=slide_count,
    )
    try:
        result = await gemini_client.generate_json(combined_prompt)
    except Exception as exc:
        logger.error(f"Generation failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Content analysis failed: {exc}")

    # Extract analysis fields for outline building
    analysis = {
        "title": result.get("title", prompt[:60]),
        "summary": result.get("summary", prompt),
        "audience": result.get("audience", "General audience"),
        "tone": result.get("tone", "professional"),
        "estimated_slides": slide_count,
        "sections": result.get("sections", []),
    }

    # Build outline deterministically from sections
    outline = _build_outline(analysis)

    # Use slide contents from the combined response
    contents: list[dict] = result.get("slides", [])

    # Pad/trim to match outline length
    empty = {"heading": "", "body": "", "bullets": [], "stats": [], "quote": "", "caption": ""}
    while len(contents) < len(outline):
        contents.append(dict(empty))
    contents = contents[: len(outline)]

    # 4. Load default theme (first theme in DB)
    theme = (await db.execute(select(Theme))).scalars().first()
    if not theme:
        raise HTTPException(status_code=500, detail="No theme found in database")

    # 5. Load any template (needed for TemplateMappingResult)
    template = (await db.execute(select(Template))).scalars().first()
    if not template:
        raise HTTPException(status_code=500, detail="No templates found in database")

    # 6. Render slides locally — pure Python layout engine
    mapping = TemplateMappingResult(template=template, theme=theme)
    agent = SlideGeneratorAgent()
    slides = agent._build_slides(outline, contents, mapping, logo_url="")

    theme_dict = {
        "id": str(theme.id),
        "name": theme.name,
        "colors": theme.colors,
        "fonts": theme.fonts,
    }

    logger.info(f"Sync generation complete: {len(slides)} slides for user {current_user.id}")
    return PreviewResponse(slides=slides, theme=theme_dict)
