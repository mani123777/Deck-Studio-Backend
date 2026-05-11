from __future__ import annotations

import asyncio
import base64
from contextvars import ContextVar
import json
import random
import re
from typing import Any

import httpx

from app.config import settings
from app.core.exceptions import GeminiError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MODEL = "gemini-2.5-flash"
_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"
_TIMEOUT = 60.0  # research summary prompts can be 100KB+, give them room
_IMAGE_MODEL = "gemini-2.5-flash-image"
_IMAGE_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_IMAGE_MODEL}:generateContent"
_IMAGE_TIMEOUT = 60.0

# Status codes that indicate transient Google-side overload — worth retrying.
_RETRYABLE_STATUSES = {500, 502, 503, 504}
_LAST_TOKEN_COUNT: ContextVar[int] = ContextVar("last_gemini_token_count", default=0)


def _record_usage(data: dict[str, Any]) -> None:
    usage = data.get("usageMetadata") or data.get("usage_metadata") or {}
    total = usage.get("totalTokenCount") or usage.get("total_token_count") or 0
    try:
        _LAST_TOKEN_COUNT.set(max(0, int(total)))
    except (TypeError, ValueError):
        _LAST_TOKEN_COUNT.set(0)


def get_last_token_count() -> int:
    return _LAST_TOKEN_COUNT.get()


async def _sleep_with_backoff(attempt: int) -> None:
    # Exponential backoff with jitter: ~1s, 2s, 4s, 8s, capped at 16s.
    delay = min(16.0, (2 ** attempt) * 1.0) + random.uniform(0, 0.5)
    await asyncio.sleep(delay)


def init_gemini() -> None:
    logger.info("Gemini client ready (REST)")


async def generate_json(prompt: str, retries: int = 4) -> Any:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    params = {"key": settings.GEMINI_API_KEY}

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(retries):
            try:
                resp = await client.post(_REST_URL, params=params, json=payload)

                if resp.status_code in _RETRYABLE_STATUSES:
                    last_exc = GeminiError(f"Gemini {resp.status_code}: {resp.text[:200]}")
                    logger.warning(
                        f"Gemini {resp.status_code} on attempt {attempt + 1}/{retries}, "
                        f"retrying with backoff…"
                    )
                    if attempt < retries - 1:
                        await _sleep_with_backoff(attempt)
                        continue
                    # Last attempt — fall through to raise below.

                if resp.status_code == 429:
                    body = resp.json()
                    msg = json.dumps(body)
                    logger.error(f"Gemini 429 on attempt {attempt + 1}: {msg[:200]}")
                    # Quota errors aren't going to clear in 8 seconds — fail fast.
                    raise GeminiError(f"Quota exceeded: {msg}")

                resp.raise_for_status()
                data = resp.json()
                _record_usage(data)
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if raw.startswith("```"):
                    lines = raw.split("\n")
                    raw = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])
                return json.loads(raw)
            except GeminiError:
                raise
            except json.JSONDecodeError as exc:
                last_exc = exc
                logger.info(f"JSON parse failed on attempt {attempt + 1}, retrying...")
                if attempt < retries - 1:
                    await _sleep_with_backoff(attempt)
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Gemini error attempt {attempt + 1}: {exc}")
                if attempt < retries - 1:
                    await _sleep_with_backoff(attempt)

    raise GeminiError(f"Gemini failed after {retries} attempts: {last_exc}")


async def generate_json_multimodal(
    prompt: str,
    images: list[tuple[bytes, str]],
    retries: int = 2,
) -> Any:
    """Like generate_json, but with one or more inline images attached.

    images: list of (raw_bytes, mime_type) — e.g. [(b"...", "image/png")].
    """
    parts: list[dict] = [{"text": prompt}]
    for img_bytes, mime in images:
        parts.append({
            "inline_data": {
                "mime_type": mime or "image/png",
                "data": base64.b64encode(img_bytes).decode(),
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    params = {"key": settings.GEMINI_API_KEY}

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT * 2) as client:
        for attempt in range(retries):
            try:
                resp = await client.post(_REST_URL, params=params, json=payload)
                if resp.status_code == 429:
                    raise GeminiError(f"Quota exceeded: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
                _record_usage(data)
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if raw.startswith("```"):
                    lines = raw.split("\n")
                    raw = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])
                return json.loads(raw)
            except GeminiError:
                raise
            except json.JSONDecodeError as exc:
                last_exc = exc
                logger.info(f"Multimodal JSON parse failed on attempt {attempt + 1}, retrying...")
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Gemini multimodal error attempt {attempt + 1}: {exc}")

    raise GeminiError(f"Gemini multimodal failed after {retries} attempts: {last_exc}")


async def generate_image(prompt: str) -> tuple[bytes, str]:
    """Generate a single image from a text prompt.

    Returns (raw_bytes, mime_type). Uses gemini-2.5-flash-image (Nano Banana).
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    params = {"key": settings.GEMINI_API_KEY}

    async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT) as client:
        resp = await client.post(_IMAGE_REST_URL, params=params, json=payload)
        if resp.status_code == 429:
            raise GeminiError(f"Quota exceeded: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise GeminiError(f"Image generation failed: {resp.status_code} {resp.text[:200]}")

        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise GeminiError(f"Unexpected image response shape: {exc}") from exc

        for part in parts:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                return base64.b64decode(inline["data"]), mime

        raise GeminiError("No image data in response")
