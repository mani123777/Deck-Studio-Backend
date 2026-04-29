from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.core.exceptions import GeminiError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MODEL = "gemini-2.5-flash"
_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"
_TIMEOUT = 30.0


def init_gemini() -> None:
    logger.info("Gemini client ready (REST)")


async def generate_json(prompt: str, retries: int = 2) -> Any:
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
                if resp.status_code == 429:
                    body = resp.json()
                    msg = json.dumps(body)
                    logger.error(f"Gemini 429 on attempt {attempt + 1}: {msg[:200]}")
                    raise GeminiError(f"Quota exceeded: {msg}")
                resp.raise_for_status()
                data = resp.json()
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
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Gemini error attempt {attempt + 1}: {exc}")

    raise GeminiError(f"Gemini failed after {retries} attempts: {last_exc}")
