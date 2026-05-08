from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gemini_client
from app.ai.prompt_templates import COMBINED_GENERATION_PROMPT, render
from app.api.dependencies import get_current_user
from app.api.v1.generate_sync import _extract_file_text, _extract_url_text
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.theme import Theme
from app.models.user import User
from app.utils.logger import get_logger

router = APIRouter(prefix="/generate", tags=["generation"])
logger = get_logger(__name__)


def _sse(event: str, data: dict | list | str) -> str:
    """Format a Server-Sent Event line."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_generation(
    prompt: str,
    slide_count: int,
    file_text: str,
    url_text: str,
    images: list[tuple[bytes, str]],
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Drive generation step-by-step, emitting SSE events as work progresses."""
    from app.agents.generation.preview_generator_agent import _build_outline
    from app.agents.generation.slide_generator_agent import (
        SlideGeneratorAgent,
        _layout_blocks,
        _content_to_blocks,
        _slide_background,
        _system_layout,
    )
    from app.agents.generation.template_mapper_agent import TemplateMappingResult

    yield _sse("status", {"step": "analyzing", "message": "Reading your source material…"})

    parts: list[str] = []
    if prompt:
        parts.append(prompt)
    if file_text:
        parts.append(file_text)
    if url_text:
        parts.append(url_text)
    content = "\n\n".join(parts) if parts else "Use the attached image(s) as the primary source."
    if not prompt:
        prompt = "Create a presentation from the provided source material."

    combined_prompt = render(
        COMBINED_GENERATION_PROMPT,
        prompt=prompt,
        content=content,
        slide_count=slide_count,
    )
    if images:
        combined_prompt += (
            "\n\nThe attached images are part of the source material. "
            "Read text/charts/data from them and use those facts in slides."
        )

    try:
        if images:
            result = await gemini_client.generate_json_multimodal(combined_prompt, images)
        else:
            result = await gemini_client.generate_json(combined_prompt)
    except Exception as exc:
        logger.error(f"Streaming generation: analysis failed: {exc}")
        yield _sse("error", {"message": f"Generation failed: {exc}"})
        return

    analysis = {
        "title": result.get("title", prompt[:60]),
        "summary": result.get("summary", prompt),
        "audience": result.get("audience", "General audience"),
        "tone": result.get("tone", "professional"),
        "estimated_slides": slide_count,
        "sections": result.get("sections", []),
    }
    yield _sse("analysis", analysis)

    outline = _build_outline(analysis)
    yield _sse("outline", {"slide_count": len(outline), "titles": [o.get("title", "") for o in outline]})

    # Theme: load default
    theme = (await db.execute(select(Theme))).scalars().first()
    if not theme:
        yield _sse("error", {"message": "No theme found"})
        return
    theme_dict = {
        "id": str(theme.id),
        "name": theme.name,
        "colors": theme.colors,
        "fonts": theme.fonts,
    }
    yield _sse("theme", theme_dict)

    # Use slide contents from the analysis call (single-call mode) and just emit
    # them one-by-one with the layout applied. This keeps the API call count to
    # one while still letting the UI render progressively.
    contents: list[dict] = result.get("slides", [])
    empty = {"heading": "", "body": "", "bullets": [], "stats": [], "quote": "", "caption": ""}
    while len(contents) < len(outline):
        contents.append(dict(empty))
    contents = contents[: len(outline)]

    theme_colors = theme.colors
    theme_fonts = theme.fonts
    content_idx = 0
    for i, (outline_item, slide_content) in enumerate(zip(outline, contents)):
        slide_type = outline_item.get("type", "content")
        slide_layout = _system_layout(slide_type, slide_content, slide_index=content_idx)
        if slide_type not in ("title", "closing"):
            content_idx += 1

        gen_blocks = _content_to_blocks(slide_content, slide_type)
        blocks = _layout_blocks(slide_type, slide_layout, gen_blocks, theme_colors, theme_fonts)
        background = _slide_background(slide_type, slide_layout, "", theme_colors)

        slide = {
            "order": outline_item.get("order", i + 1),
            "type": slide_type,
            "background": background,
            "blocks": blocks,
        }
        yield _sse("slide", {"index": i, "total": len(outline), "slide": slide})
        # tiny pause so the browser actually flushes between events
        await asyncio.sleep(0.02)

    yield _sse("complete", {"slide_count": len(outline)})


@router.post("/stream")
@limiter.limit("20/hour")
async def generate_stream(
    request: Request,
    prompt: str = Form(""),
    slide_count: int = Form(10),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    images: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events endpoint that streams slides as they're produced.

    Events: status, analysis, outline, theme, slide (one per slide), complete, error.
    """
    slide_count = max(5, min(20, slide_count))

    file_text = ""
    if file and file.filename:
        try:
            file_text = await _extract_file_text(file)
            if len(file_text) > 50_000:
                file_text = file_text[:50_000] + "\n...[content truncated]"
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"File extraction failed, ignoring file: {exc}")

    url_text = ""
    url_value = (url or "").strip()
    if url_value:
        title, page_text = await _extract_url_text(url_value)
        if len(page_text) > 50_000:
            page_text = page_text[:50_000] + "\n...[content truncated]"
        url_text = f"Source: {url_value}\nTitle: {title}\n\n{page_text}"

    image_payloads: list[tuple[bytes, str]] = []
    MAX_IMAGES = 4
    MAX_IMAGE_BYTES = 5 * 1024 * 1024
    for img in (images or [])[:MAX_IMAGES]:
        if not img or not img.filename:
            continue
        mime = (img.content_type or "image/png").lower()
        if not mime.startswith("image/"):
            continue
        data = await img.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail=f"Image '{img.filename}' exceeds 5 MB limit.")
        if data:
            image_payloads.append((data, mime))

    if not (prompt or file_text or url_text or image_payloads):
        raise HTTPException(
            status_code=400,
            detail="Provide a prompt, a document, a URL, or at least one image.",
        )

    return StreamingResponse(
        _stream_generation(prompt, slide_count, file_text, url_text, image_payloads, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx, etc)
        },
    )
