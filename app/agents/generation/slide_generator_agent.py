from __future__ import annotations

import asyncio
import json
from typing import Any

from app.ai import gemini_client
from app.ai.prompt_templates import SLIDE_CONTENT_PROMPT, render
from app.agents.generation.template_mapper_agent import TemplateMappingResult
from app.utils.logger import get_logger

logger = get_logger(__name__)

W, H = 1280, 720


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _premium_card_pair(theme_colors: dict) -> tuple[str, str, str, str]:
    """Return (dark_bg, dark_text, light_bg, light_text) for alternating cards."""
    primary = theme_colors.get("primary", "#0F172A")
    surface = theme_colors.get("surface", "#F1F5F9")
    text_col = theme_colors.get("text", "#0F172A")
    return primary, "#ffffff", surface, text_col


def _is_card_dark(idx: int) -> bool:
    """Gamma-style: top-left and bottom-right are dark, others light."""
    return idx in (0, 3)


def _layout_blocks(
    slide_type: str,
    slide_layout: str,
    gen_blocks: list[dict],
    theme_colors: dict,
    theme_fonts: dict,
) -> list[dict]:
    primary   = theme_colors.get("primary",    "#0F172A")
    secondary = theme_colors.get("secondary",  "#1E293B")
    accent    = theme_colors.get("accent",     "#6366F1")
    bg_col    = theme_colors.get("background", "#FFFFFF")
    text_col  = theme_colors.get("text",       "#0F172A")
    surface   = theme_colors.get("surface",    "#F1F5F9")

    hfam = theme_fonts.get("heading", {}).get("family", "Inter, sans-serif")
    bfam = theme_fonts.get("body",    {}).get("family", "Inter, sans-serif")

    dark_card_bg, dark_card_text, light_card_bg, light_card_text = _premium_card_pair(theme_colors)

    blocks_out: list[dict] = []

    # ── Block factory ──────────────────────────────────────────────────────
    def _b(bid, btype, content, x, y, w, h, *,
           size=16, weight=400, color=None, align="left", family=None, bg="transparent"):
        return {
            "id": bid, "type": btype, "content": content,
            "position": {"x": x, "y": y, "w": w, "h": h},
            "styling": {
                "font_family": family or bfam,
                "font_size": size, "font_weight": weight,
                "color": color or text_col,
                "background_color": bg, "text_align": align,
            },
        }

    def _badge(label: str, x: int = 60, y: int = 35) -> dict | None:
        if not label:
            return None
        return {
            "id": "badge", "type": "badge", "content": label,
            "position": {"x": x, "y": y, "w": max(140, len(label) * 9 + 32), "h": 28},
            "styling": {
                "font_family": bfam, "font_size": 11, "font_weight": 700,
                "color": accent, "background_color": "transparent", "text_align": "left",
            },
        }

    def _accent_bar(x: int, y: int, w: int = 80, h: int = 4) -> dict:
        return {
            "id": f"accent-{x}-{y}", "type": "shape", "content": "",
            "position": {"x": x, "y": y, "w": w, "h": h},
            "styling": {
                "font_family": "", "font_size": 0, "font_weight": 0,
                "color": accent, "background_color": accent, "text_align": "left",
            },
        }

    def _panel(bid: str, x: int, y: int, w: int, h: int, gradient: str) -> dict:
        """Full gradient decorative panel — Gamma's image-panel replacement."""
        return {
            "id": bid, "type": "panel", "content": "",
            "position": {"x": x, "y": y, "w": w, "h": h},
            "styling": {
                "font_family": "", "font_size": 0, "font_weight": 0,
                "color": "transparent", "background_color": gradient, "text_align": "left",
            },
        }

    # ── Index gen_blocks by type ───────────────────────────────────────────
    by_type: dict[str, list[dict]] = {}
    for gb in gen_blocks:
        by_type.setdefault(gb.get("type", "body"), []).append(gb)

    def _get(btype: str, fallback: str = "") -> str:
        lst = by_type.get(btype, [])
        if lst:
            b = lst.pop(0)
            items = b.get("items", [])
            return "\n".join(items) if items else b.get("content", fallback)
        return fallback

    def _bullets() -> list[str]:
        out: list[str] = []
        for gb in gen_blocks:
            if gb.get("type") in ("bullet", "body"):
                items = gb.get("items", [])
                if items:
                    out.extend(items)
                elif gb.get("content"):
                    out.append(gb["content"])
        return out

    BADGE_LABELS = {
        "agenda":  "OVERVIEW",
        "content": "KEY INSIGHTS",
        "stats":   "METRICS",
        "quote":   "PERSPECTIVE",
    }
    badge_label = BADGE_LABELS.get(slide_type, "KEY INSIGHTS")

    layout = slide_layout or ""

    # ── title_hero ──────────────────────────────────────────────────────────
    if slide_type == "title" or layout == "title_hero":
        title_text = _get("title", "Presentation Title")
        sub_text   = _get("subtitle", "")

        blocks_out.append(_b("title", "title", title_text,
                              100, 210, 1080, 170,
                              size=68, weight=800, color="#ffffff",
                              align="center", family=hfam))
        blocks_out.append(_accent_bar(560, 402, 160, 5))
        if sub_text:
            blocks_out.append(_b("subtitle", "subtitle", sub_text,
                                  100, 425, 1080, 70,
                                  size=22, weight=400,
                                  color="rgba(255,255,255,0.78)", align="center"))

    # ── agenda_rows ─────────────────────────────────────────────────────────
    elif slide_type == "agenda" or layout == "agenda_rows":
        heading = _get("heading", _get("title", "Agenda"))
        bullets  = _bullets()

        bdg = _badge(badge_label)
        if bdg:
            blocks_out.append(bdg)
        blocks_out.append(_b("heading", "heading", heading,
                              60, 68, 900, 80,
                              size=44, weight=800, color=primary,
                              align="left", family=hfam))
        blocks_out.append(_accent_bar(60, 158, 100, 4))

        for idx, b in enumerate(bullets[:6]):
            clean = b.lstrip("•-* ").strip()
            cy = 178 + idx * 82
            is_dark = idx % 2 == 0
            card_bg   = dark_card_bg   if is_dark else light_card_bg
            card_text = dark_card_text if is_dark else light_card_text
            blocks_out.append({
                "id": f"agenda-row-{idx}", "type": "card",
                "content": f"{idx + 1:02d}  {clean}",
                "position": {"x": 60, "y": cy, "w": 1160, "h": 68},
                "styling": {
                    "font_family": hfam, "font_size": 20, "font_weight": 600,
                    "color": card_text, "background_color": card_bg, "text_align": "left",
                },
            })

    # ── split_panel (Gamma hero: gradient panel left + cards right) ─────────
    elif layout == "split_panel":
        heading     = _get("heading", _get("title", "Section"))
        bullets_raw = _bullets()

        panel_grad = f"linear-gradient(160deg, {primary} 0%, {secondary} 65%, {accent}55 100%)"
        blocks_out.append(_panel("left-panel", 0, 0, 490, 720, panel_grad))
        # Accent dot on panel
        blocks_out.append({
            "id": "panel-dot", "type": "shape", "content": "",
            "position": {"x": 420, "y": 320, "w": 40, "h": 40},
            "styling": {
                "font_family": "", "font_size": 0, "font_weight": 0,
                "color": accent, "background_color": f"{accent}60", "text_align": "left",
            },
        })

        rx = 530
        rw = 710

        bdg = _badge(badge_label, rx, 35)
        if bdg:
            blocks_out.append(bdg)

        blocks_out.append(_b("heading", "heading", heading,
                              rx, 75, rw, 100,
                              size=40, weight=800, color=primary,
                              align="left", family=hfam))

        card_w = (rw - 20) // 2   # 345
        card_h = 185

        for idx, btext in enumerate(bullets_raw[:4]):
            parts = btext.split(": ", 1) if ": " in btext else [btext, ""]
            title_line = parts[0]
            body_line  = parts[1] if len(parts) > 1 else ""
            content_str = f"{title_line}\n{body_line}" if body_line else title_line

            col = idx % 2
            row = idx // 2
            cx  = rx + col * (card_w + 20)
            cy  = 195 + row * (card_h + 15)

            is_dark   = _is_card_dark(idx)
            card_bg   = dark_card_bg   if is_dark else light_card_bg
            card_text = dark_card_text if is_dark else light_card_text

            blocks_out.append({
                "id": f"card-{idx}", "type": "card", "content": content_str,
                "position": {"x": cx, "y": cy, "w": card_w, "h": card_h},
                "styling": {
                    "font_family": hfam, "font_size": 17, "font_weight": 700,
                    "color": card_text, "background_color": card_bg, "text_align": "left",
                },
            })

        if not bullets_raw:
            body_text = _get("body", "")
            blocks_out.append(_b("body", "bullet", body_text,
                                  rx, 195, rw, 460,
                                  size=22, weight=400, color=text_col))

    # ── card_grid (full-width 2×2) ────────────────────────────────────────
    elif layout == "card_grid":
        heading     = _get("heading", _get("title", "Overview"))
        bullets_raw = _bullets()

        bdg = _badge(badge_label)
        if bdg:
            blocks_out.append(bdg)
        blocks_out.append(_b("heading", "heading", heading,
                              60, 68, 1160, 80,
                              size=44, weight=800, color=primary,
                              align="left", family=hfam))
        blocks_out.append(_accent_bar(60, 158, 100, 4))

        card_w, card_h = 570, 210

        for idx, btext in enumerate(bullets_raw[:4]):
            col = idx % 2
            row = idx // 2
            cx  = 60  + col * (card_w + 40)
            cy  = 178 + row * (card_h + 20)

            is_dark   = _is_card_dark(idx)
            card_bg   = dark_card_bg   if is_dark else light_card_bg
            card_text = dark_card_text if is_dark else light_card_text

            blocks_out.append({
                "id": f"card-{idx}", "type": "card", "content": btext,
                "position": {"x": cx, "y": cy, "w": card_w, "h": card_h},
                "styling": {
                    "font_family": hfam, "font_size": 20, "font_weight": 700,
                    "color": card_text, "background_color": card_bg, "text_align": "left",
                },
            })

    # ── stats_showcase ────────────────────────────────────────────────────
    elif slide_type == "stats" or layout == "stats_showcase":
        heading = _get("heading", _get("title", "Key Metrics"))
        stats   = by_type.get("stat", [])
        if not stats:
            stats = [{"id": f"s{i}", "content": f"Metric {i+1}"} for i in range(3)]

        bdg = _badge(badge_label)
        if bdg:
            blocks_out.append(bdg)
        blocks_out.append(_b("heading", "heading", heading,
                              60, 68, 1160, 80,
                              size=44, weight=800, color="#ffffff",
                              align="center", family=hfam))
        blocks_out.append(_accent_bar(560, 158, 160, 5))

        n = min(len(stats), 4)
        if n <= 2:
            stat_w = 460
            total  = n * stat_w + (n - 1) * 40
            sx0    = (W - total) // 2
            for idx, stat in enumerate(stats[:n]):
                sx = sx0 + idx * (stat_w + 40)
                blocks_out.append({
                    "id": stat.get("id", f"stat-{idx}"), "type": "stat",
                    "content": stat.get("content", "—"),
                    "position": {"x": sx, "y": 220, "w": stat_w, "h": 290},
                    "styling": {
                        "font_family": hfam, "font_size": 72, "font_weight": 800,
                        "color": accent,
                        "background_color": "rgba(255,255,255,0.08)", "text_align": "center",
                    },
                })
        else:
            stat_w, stat_h = 560, 210
            for idx, stat in enumerate(stats[:4]):
                col = idx % 2
                row = idx // 2
                sx  = 60  + col * (stat_w + 40)
                sy  = 180 + row * (stat_h + 20)
                blocks_out.append({
                    "id": stat.get("id", f"stat-{idx}"), "type": "stat",
                    "content": stat.get("content", "—"),
                    "position": {"x": sx, "y": sy, "w": stat_w, "h": stat_h},
                    "styling": {
                        "font_family": hfam, "font_size": 60, "font_weight": 800,
                        "color": accent,
                        "background_color": "rgba(255,255,255,0.08)", "text_align": "center",
                    },
                })

    # ── quote_centered ─────────────────────────────────────────────────────
    elif slide_type == "quote" or layout == "quote_centered":
        quote_text  = _get("quote",   _get("body", "Inspiring words go here."))
        attribution = _get("caption", "— Author")

        blocks_out.append(_b("quote-mark", "text", "“",
                              80, 50, 200, 140,
                              size=160, weight=900, color=accent,
                              align="left", family=hfam))
        blocks_out.append(_b("quote-text", "quote", quote_text,
                              80, 175, 1120, 330,
                              size=32, weight=400, color="#ffffff",
                              align="center", family=hfam))
        blocks_out.append(_b("attribution", "caption", attribution,
                              80, 530, 1120, 50,
                              size=18, weight=600, color=accent, align="center"))

    # ── process_steps ─────────────────────────────────────────────────────
    elif layout == "process_steps":
        heading     = _get("heading", _get("title", "Process"))
        bullets_raw = _bullets()
        if not bullets_raw:
            bullets_raw = ["Step 1", "Step 2", "Step 3"]

        bdg = _badge(badge_label)
        if bdg:
            blocks_out.append(bdg)
        blocks_out.append(_b("heading", "heading", heading,
                              60, 68, 1160, 80,
                              size=44, weight=800, color=primary,
                              align="left", family=hfam))
        blocks_out.append(_accent_bar(60, 158, 100, 4))

        n       = min(len(bullets_raw), 4)
        step_w  = min(240, (W - 120 - (n - 1) * 20) // n)
        total_w = n * step_w + (n - 1) * 20
        start_x = (W - total_w) // 2

        for idx, btext in enumerate(bullets_raw[:n]):
            cx = start_x + idx * (step_w + 20)
            blocks_out.append({
                "id": f"step-num-{idx}", "type": "process_circle",
                "content": str(idx + 1),
                "position": {"x": cx + step_w // 2 - 40, "y": 210, "w": 80, "h": 80},
                "styling": {
                    "font_family": hfam, "font_size": 32, "font_weight": 800,
                    "color": "#ffffff", "background_color": accent, "text_align": "center",
                },
            })
            if idx < n - 1:
                blocks_out.append({
                    "id": f"connector-{idx}", "type": "shape", "content": "",
                    "position": {"x": cx + step_w + 25, "y": 248, "w": 15, "h": 4},
                    "styling": {
                        "font_family": "", "font_size": 0, "font_weight": 0,
                        "color": accent, "background_color": accent, "text_align": "left",
                    },
                })
            blocks_out.append(_b(f"step-{idx}", "text", btext,
                                  cx, 310, step_w, 180,
                                  size=15, weight=600, color=text_col, align="center", family=hfam))

    # ── closing ────────────────────────────────────────────────────────────
    elif slide_type == "closing" or layout == "closing":
        cta = _get("title",    "Let's Get Started")
        sub = _get("subtitle", _get("body", "Contact us to learn more"))

        blocks_out.append(_accent_bar(480, 190, 320, 5))
        blocks_out.append(_b("cta", "title", cta,
                              80, 215, 1120, 170,
                              size=64, weight=800, color="#ffffff",
                              align="center", family=hfam))
        if sub:
            blocks_out.append(_b("sub", "subtitle", sub,
                                  80, 410, 1120, 70,
                                  size=22, weight=400,
                                  color="rgba(255,255,255,0.75)", align="center"))

    # ── content_clean (fallback) ───────────────────────────────────────────
    else:
        heading     = _get("heading", _get("title", "Section Title"))
        body_text   = _get("body", "")
        bullets_raw = _bullets()

        bdg = _badge(badge_label)
        if bdg:
            blocks_out.append(bdg)
        blocks_out.append(_b("heading", "heading", heading,
                              60, 68, 1160, 80,
                              size=44, weight=800, color=primary,
                              align="left", family=hfam))
        blocks_out.append(_accent_bar(60, 158, 100, 4))

        bullet_text = "\n".join(f"• {b}" for b in bullets_raw if b)
        if not bullet_text:
            bullet_text = body_text
        blocks_out.append(_b("body", "bullet", bullet_text,
                              60, 182, 1160, 490,
                              size=24, weight=400, color=text_col))

    return [b for b in blocks_out if b]


def _slide_background(slide_type: str, slide_layout: str, _kw: str, theme_colors: dict) -> dict:
    primary   = theme_colors.get("primary",    "#0F172A")
    secondary = theme_colors.get("secondary",  "#1E293B")
    accent    = theme_colors.get("accent",     "#6366F1")
    bg        = theme_colors.get("background", "#FFFFFF")

    if slide_type in ("title", "closing") or slide_layout in ("title_hero", "closing"):
        return {
            "type": "gradient",
            "value": f"linear-gradient(135deg, {primary} 0%, {secondary} 70%, {accent}50 100%)",
        }
    if slide_type == "quote" or slide_layout == "quote_centered":
        return {
            "type": "gradient",
            "value": f"linear-gradient(160deg, {primary} 0%, {secondary} 100%)",
        }
    if slide_type == "stats" or slide_layout == "stats_showcase":
        return {
            "type": "gradient",
            "value": f"linear-gradient(135deg, {secondary} 0%, {primary} 100%)",
        }
    return {"type": "color", "value": bg}


def _system_layout(slide_type: str, content: dict, slide_index: int = 0) -> str:
    if slide_type == "title":   return "title_hero"
    if slide_type == "closing": return "closing"
    if slide_type == "agenda":  return "agenda_rows"
    if slide_type == "stats" or content.get("stats"): return "stats_showcase"
    if slide_type == "quote"  or content.get("quote"): return "quote_centered"

    bullets = content.get("bullets", [])
    heading = content.get("heading", "").lower()
    body    = content.get("body",    "")

    process_words = ("process", "step", "phase", "how", "workflow", "pipeline", "framework", "journey")
    if any(w in heading for w in process_words) and 2 <= len(bullets) <= 5:
        return "process_steps"

    if 2 <= len(bullets) <= 5:
        return "split_panel" if slide_index % 2 == 0 else "card_grid"

    return "content_clean"


def _content_to_blocks(content: dict, slide_type: str) -> list[dict]:
    blocks: list[dict] = []
    heading = content.get("heading", "")
    body    = content.get("body",    "")
    bullets = content.get("bullets", [])
    stats   = content.get("stats",   [])
    quote   = content.get("quote",   "")
    caption = content.get("caption", "")

    if slide_type in ("title", "closing"):
        if heading:
            blocks.append({"id": "title-0", "type": "title",    "content": heading})
        sub = bullets[0] if bullets else body
        if sub:
            blocks.append({"id": "subtitle-0", "type": "subtitle", "content": sub})

    elif slide_type == "quote":
        if quote:
            blocks.append({"id": "quote-0",   "type": "quote",   "content": quote})
        if caption:
            blocks.append({"id": "caption-0", "type": "caption", "content": caption})

    elif slide_type == "stats":
        if heading:
            blocks.append({"id": "heading-0", "type": "heading", "content": heading})
        for idx, s in enumerate(stats):
            parts     = s.split(maxsplit=1)
            formatted = f"{parts[0]}\n{parts[1]}" if len(parts) > 1 else s
            blocks.append({"id": f"stat-{idx}", "type": "stat", "content": formatted})

    else:
        if heading:
            blocks.append({"id": "heading-0", "type": "heading", "content": heading})
        if body:
            blocks.append({"id": "body-0",    "type": "body",    "content": body})
        for idx, b in enumerate(bullets):
            blocks.append({"id": f"bullet-{idx}", "type": "bullet", "content": b})

    return blocks


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SlideGeneratorAgent:
    async def run(
        self,
        outline: list[dict],
        analysis: dict[str, Any],
        mapping: TemplateMappingResult,
        logo_url: str = "",
        max_concurrency: int = 3,
    ) -> list[dict]:
        analysis_summary = json.dumps(analysis, indent=2)
        outline_summary = json.dumps(
            [
                {
                    "order": item.get("order"),
                    "type": item.get("type"),
                    "title": item.get("title"),
                    "key_points": item.get("key_points", []),
                }
                for item in outline
            ],
            indent=2,
        )
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _throttled(item: dict) -> dict:
            async with semaphore:
                return await self._generate_slide_content(item, analysis_summary, outline_summary)

        logger.info(f"Generating {len(outline)} slides (max {max_concurrency} concurrent)")
        contents = await asyncio.gather(*[_throttled(item) for item in outline])
        return self._build_slides(outline, list(contents), mapping, logo_url)

    async def _generate_slide_content(
        self, outline_item: dict, analysis_summary: str, full_outline: str
    ) -> dict:
        prompt = render(
            SLIDE_CONTENT_PROMPT,
            outline_item=json.dumps(outline_item, indent=2),
            full_outline=full_outline,
            analysis_summary=analysis_summary,
            slide_type=outline_item.get("type", "content"),
        )
        return await gemini_client.generate_json(prompt)

    def _build_slides(
        self,
        outline: list[dict],
        contents: list[dict],
        mapping: TemplateMappingResult,
        logo_url: str,
    ) -> list[dict]:
        theme_colors = mapping.theme.colors
        theme_fonts  = mapping.theme.fonts
        result: list[dict] = []
        content_idx = 0

        for i, (outline_item, content) in enumerate(zip(outline, contents)):
            slide_type  = outline_item.get("type", "content")
            slide_layout = _system_layout(slide_type, content, slide_index=content_idx)
            if slide_type not in ("title", "closing"):
                content_idx += 1

            gen_blocks = _content_to_blocks(content, slide_type)
            blocks     = _layout_blocks(slide_type, slide_layout, gen_blocks, theme_colors, theme_fonts)
            background = _slide_background(slide_type, slide_layout, "", theme_colors)

            result.append({
                "order":      outline_item.get("order", i + 1),
                "type":       slide_type,
                "background": background,
                "blocks":     blocks,
            })

        return result
