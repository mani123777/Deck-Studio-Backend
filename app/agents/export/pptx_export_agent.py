from __future__ import annotations

from pathlib import Path

from app.core.storage import export_path
from app.models.presentation import Presentation
from app.models.theme import Theme
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 1920x1080 design space -> pptx inches (at 96 dpi)
DESIGN_W = 1920
DESIGN_H = 1080
SLIDE_W_IN = 13.33
SLIDE_H_IN = 7.5


def _px_to_emu(px: float, design_dim: float, slide_dim_in: float) -> int:
    """Convert design-space pixels to EMU."""
    inches = (px / design_dim) * slide_dim_in
    return int(inches * 914400)


class PptxExportAgent:
    async def run(self, presentation: Presentation, theme: Theme) -> Path:
        from pptx import Presentation as PptxPresentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor

        prs = PptxPresentation()
        prs.slide_width = Inches(SLIDE_W_IN)
        prs.slide_height = Inches(SLIDE_H_IN)

        blank_layout = prs.slide_layouts[6]  # blank layout

        colors = theme.colors  # dict
        fonts = theme.fonts    # dict

        def hex_to_rgb(hex_color: str) -> RGBColor:
            h = hex_color.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return RGBColor(r, g, b)

        for slide_data in sorted(presentation.slides or [], key=lambda s: s.get("order", 0)):
            pptx_slide = prs.slides.add_slide(blank_layout)

            # Set background color from theme
            bg_color = colors.get("background", "")
            if bg_color and bg_color != "transparent":
                bg = pptx_slide.background
                fill = bg.fill
                fill.solid()
                try:
                    fill.fore_color.rgb = hex_to_rgb(bg_color)
                except Exception:
                    pass

            for block in slide_data.get("blocks", []):
                if block.get("type") == "image":
                    continue

                pos = block.get("position", {"x": 0, "y": 0, "w": 100, "h": 100})
                styling = block.get("styling", {})

                left = _px_to_emu(pos.get("x", 0), DESIGN_W, SLIDE_W_IN)
                top = _px_to_emu(pos.get("y", 0), DESIGN_H, SLIDE_H_IN)
                width = _px_to_emu(pos.get("w", 100), DESIGN_W, SLIDE_W_IN)
                height = _px_to_emu(pos.get("h", 100), DESIGN_H, SLIDE_H_IN)

                txBox = pptx_slide.shapes.add_textbox(left, top, width, height)
                tf = txBox.text_frame
                tf.word_wrap = True

                p = tf.paragraphs[0]
                content = block.get("content", "")
                p.text = content

                run = p.runs[0] if p.runs else p.add_run()
                run.text = content

                font = run.font
                font.size = Pt(styling.get("font_size", 16))
                font.bold = styling.get("font_weight", 400) >= 700
                try:
                    font.color.rgb = hex_to_rgb(styling.get("color", "#000000"))
                except Exception:
                    pass

                from pptx.enum.text import PP_ALIGN
                align_map = {
                    "left": PP_ALIGN.LEFT,
                    "center": PP_ALIGN.CENTER,
                    "right": PP_ALIGN.RIGHT,
                    "justify": PP_ALIGN.JUSTIFY,
                }
                p.alignment = align_map.get(styling.get("text_align", "left"), PP_ALIGN.LEFT)

        out_path = export_path(str(presentation.id), "pptx")
        prs.save(str(out_path))
        logger.info(f"PPTX export saved to {out_path}")
        return out_path
