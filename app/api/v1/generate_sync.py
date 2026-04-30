from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from lxml import html as lxml_html
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


async def _extract_url_text(url: str) -> tuple[str, str]:
    """Fetch a URL and return (title, readable_text). Raises HTTPException on failure."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL must use http or https")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL is malformed")

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; WACDeckStudio/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not fetch URL: {exc}"
        ) from exc

    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        raise HTTPException(
            status_code=400,
            detail=f"URL returned unsupported content-type '{ctype}'.",
        )

    try:
        doc = lxml_html.fromstring(resp.text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {exc}") from exc

    # Strip noisy elements
    for tag in doc.xpath(
        "//script | //style | //noscript | //nav | //footer | //header"
        " | //aside | //form | //iframe | //svg"
    ):
        tag.getparent().remove(tag) if tag.getparent() is not None else None

    title_el = doc.find(".//title")
    title = (title_el.text_content().strip() if title_el is not None else "") or url

    # Prefer <article> / <main>; fall back to <body>
    candidates = doc.xpath("//article") or doc.xpath("//main") or doc.xpath("//body")
    root = candidates[0] if candidates else doc
    text = root.text_content()
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="No readable text found at URL.")
    return title, text


@router.post("/sync", response_model=PreviewResponse)
async def generate_sync(
    prompt: str = Form(""),
    slide_count: int = Form(10),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse:
    """
    Synchronous generation: returns {slides, theme} in one request.
    Single Gemini API call — analysis + slide content combined.

    Source content priority (concatenated, when present):
      prompt + uploaded file text + URL-fetched text
    At least one of {prompt, file, url} must be supplied.
    """
    from app.agents.generation.preview_generator_agent import _build_outline
    from app.agents.generation.slide_generator_agent import SlideGeneratorAgent
    from app.agents.generation.template_mapper_agent import TemplateMappingResult

    slide_count = max(5, min(20, slide_count))

    # Build the source content from prompt + optional file + optional url
    parts: list[str] = []
    prompt = (prompt or "").strip()
    if prompt:
        parts.append(prompt)

    if file and file.filename:
        try:
            file_text = await _extract_file_text(file)
            if len(file_text) > 50_000:
                file_text = file_text[:50_000] + "\n...[content truncated]"
            parts.append(file_text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"File extraction failed, ignoring file: {exc}")

    url_value = (url or "").strip()
    if url_value:
        title, page_text = await _extract_url_text(url_value)
        if len(page_text) > 50_000:
            page_text = page_text[:50_000] + "\n...[content truncated]"
        parts.append(f"Source: {url_value}\nTitle: {title}\n\n{page_text}")

    if not parts:
        raise HTTPException(
            status_code=400,
            detail="Provide a prompt, a document, or a URL.",
        )

    content = "\n\n".join(parts)
    # Keep `prompt` field non-empty so downstream prompt template formats cleanly
    if not prompt:
        prompt = f"Create a presentation from the provided source material."

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
