from __future__ import annotations

from string import Template

CONTENT_ANALYSIS_PROMPT = Template("""
You are an expert presentation content analyst. Analyze the following document content and extract structured information.

Document content:
$content

Return a JSON object with this exact structure:
{
  "title": "Suggested presentation title",
  "key_topics": ["topic1", "topic2", ...],
  "summary": "Brief 2-3 sentence summary of the content",
  "audience": "Target audience description",
  "tone": "professional|casual|technical|inspirational",
  "estimated_slides": <number between 8 and 15>,
  "sections": [
    {"name": "section name", "content": "key points from this section", "slide_count": <number>}
  ]
}

Respond with valid JSON only, no markdown or extra text.
""")

OUTLINE_GENERATION_PROMPT = Template("""
You are an expert presentation strategist. Your job is to create a concise, structured outline for a presentation based on the document analysis provided. Do NOT write full content — only identify the slides needed and their key points.

Document Analysis:
$analysis

Generate an outline for a presentation with $slide_count slides.

Rules:
- First slide must be type "title"
- Last slide must be type "closing"
- Include at least one "agenda" slide near the start
- Use types: title | agenda | content | quote | stats | closing
- key_points must be 2-3 short phrases (not full sentences) describing what this slide will cover
- All content must be grounded in the source document — no invented topics
- Each slide must cover a DISTINCT angle or sub-topic — key_points must NOT overlap or repeat across slides
- Slide titles must be unique; if topics are closely related, split them by depth (definition → process → examples → comparison) rather than restating the same idea

Return a JSON array with exactly $slide_count items:
[
  {
    "order": 1,
    "type": "title|agenda|content|quote|stats|closing",
    "title": "Short slide title (≤8 words)",
    "key_points": ["key point 1", "key point 2", "key point 3"]
  }
]

Respond with valid JSON array only — no markdown fences, no explanation.
""")

SLIDE_CONTENT_PROMPT = Template("""
You are an expert presentation content writer. Generate the full content for ONE slide based on the outline item and document context provided. Do NOT decide layout, colors, fonts, or visuals — the system handles all of that.

Slide Outline Item (THIS slide):
$outline_item

Full Presentation Outline (ALL slides — for context, do NOT generate content for these):
$full_outline

Full Document Context:
$analysis_summary

Slide type: $slide_type

Write content appropriate for this slide type:
- "title": strong headline (≤8 words) as heading + punchy tagline (≤15 words) as a subtitle bullet
- "agenda": heading + 4-6 section names as bullets
- "content": heading (≤6 words) + 3-5 bullets (10-20 words each, concrete and specific) + optional body paragraph
- "quote": one memorable quote (20-40 words) as quote + attribution as caption
- "stats": heading + 3-4 data points as stats in format "VALUE Label" (e.g. "47% Cost Reduction")
- "closing": call-to-action headline as heading + contact/next-step as subtitle bullet

Return a single JSON object (NOT an array):
{
  "heading": "Slide heading text",
  "body": "Optional body paragraph text (for content slides), empty string otherwise",
  "bullets": ["bullet point 1", "bullet point 2"],
  "stats": ["47% Cost Reduction", "$2.4B Market Size"],
  "quote": "Quote text if this is a quote slide, empty string otherwise",
  "caption": "Attribution or caption text, empty string if not applicable"
}

Rules:
- All fields are always present; use empty string "" or empty array [] when not applicable
- "stats" array only for stats slides; "quote" only for quote slides
- All content must come from the source document — no placeholders, no invented facts
- Restrict yourself STRICTLY to THIS slide's key_points. Do NOT repeat bullets, examples, or framings already assigned to other slides in the full outline above
- If THIS slide's topic overlaps another, focus on the unique angle implied by THIS slide's title and key_points only
- Respond with valid JSON object only — no markdown fences, no explanation
""")

PREVIEW_GENERATION_PROMPT = Template("""
You are a presentation content creator. Generate a complete sample presentation for the template "$template_name".

Template category: $category
Target audience: $audience
Theme: $theme_name

Generate a realistic sample presentation with $slide_count slides demonstrating this template's structure.

Return a JSON array of slides:
[
  {
    "order": 1,
    "type": "title",
    "blocks": [
      {
        "id": "unique-block-id",
        "type": "text|image|title|subtitle|bullet",
        "content": "sample content here"
      }
    ]
  }
]

Make the content realistic, professional, and relevant to the template's purpose.
Respond with valid JSON array only.
""")


COMBINED_GENERATION_PROMPT = Template("""
You are a professional presentation creator. Analyze the provided content and generate a complete presentation in ONE response.

User prompt: $prompt

Document content:
$content

Required slide count: $slide_count

$level_instructions

Instructions:
1. Analyze the content to extract title, summary, audience, and sections
2. Generate slide content for exactly $slide_count slides (title slide first, agenda second, closing last, content/stats in between)
3. Use type "stats" for slides with numeric data/metrics, "content" for everything else

Return ONLY this JSON structure (no markdown, no explanation):
{
  "title": "Presentation title (≤10 words)",
  "summary": "2-3 sentence summary",
  "audience": "Target audience",
  "tone": "professional",
  "sections": [
    {"name": "section name", "content": "key points", "slide_count": 1}
  ],
  "slides": [
    {
      "type": "title|agenda|content|stats|closing",
      "heading": "Slide heading (≤8 words)",
      "body": "",
      "bullets": ["bullet 1", "bullet 2"],
      "stats": [],
      "quote": "",
      "caption": ""
    }
  ]
}

Rules:
- slides array must have exactly $slide_count items
- slides[0] is always type "title"
- slides[1] is always type "agenda" with bullets listing section names
- slides[-1] is always type "closing"
- stats array only used for type "stats" slides (format: "47% Cost Reduction")
- bullets empty for title and closing slides
- All content must come from the source document — no invented facts
- All fields always present, use "" or [] when not applicable
""")


RESEARCH_SUMMARY_PROMPT = Template("""
You are a research analyst synthesizing recent news articles into structured insights for a presentation.

Topic: $topic
Audience: $audience
Style: $style

Articles (numbered, with source domain and full text):
$articles

Your job is to produce a JSON research brief. STRICT rules:
- Use ONLY facts present in the articles. If something isn't there, omit it. NEVER invent statistics, dates, or quotes.
- When citing a fact, append article numbers in brackets, e.g. "Floods displaced 2.4M people [1][3]".
- If articles disagree, surface the disagreement explicitly in `risks` or `key_points` (e.g. "Sources differ on casualty count: [1] reports 12, [4] reports 30").
- If a section has no supporting material, return an empty array/string for it — do not pad.

Return ONLY this JSON (no markdown fences, no commentary):
{
  "title": "Concise presentation title (≤10 words)",
  "overview": "2–3 sentence neutral summary of the topic.",
  "key_points": ["fact 1 [n]", "fact 2 [n]", ...],
  "timeline": [
    {"date": "ISO or human date", "event": "what happened [n]"}
  ],
  "statistics": [
    {"value": "exact number from article", "label": "what it measures", "source_index": 1}
  ],
  "trends": ["trend 1 [n]", "trend 2 [n]"],
  "risks": ["risk or open question [n]"],
  "conclusion": "1–2 sentence forward-looking takeaway, grounded in the articles.",
  "sources_used": [1, 2, 4]
}
""")


TOPIC_OUTLINE_PROMPT = Template("""
You are planning the slide order for a presentation based on a research brief.

Topic: $topic
Audience: $audience
Style: $style
Slide count target: $slide_count

Research brief (JSON):
$brief

Return ONLY a JSON array of slide intents in display order. Each item:
{"order": 1, "type": "title|agenda|content|stats|timeline|quote|closing|sources",
 "title": "slide title (≤8 words)",
 "key_points": ["talking point 1", "talking point 2"]}

Rules:
- First slide must be type "title".
- Second slide must be type "agenda" listing the major sections.
- Last slide must be type "sources" listing the article URLs that informed the deck.
- Use type "stats" for slides primarily about numeric data (values from research.statistics).
- Use type "timeline" for chronological slides if research.timeline has entries.
- Use type "content" for narrative sections.
- Length: exactly $slide_count items. Pad or condense as needed but never invent material.
""")


_SIMPLE_INSTRUCTIONS = (
    "Visual style: SIMPLE. Keep slides text-driven. Use the standard mix of "
    "title / agenda / content / stats / closing. Do not add image, chart, or "
    "process diagram blocks unless the source explicitly demands them."
)

_ADVANCED_INSTRUCTIONS = """Visual style: ADVANCED. The deck must feel visually rich and information-dense.
Make deliberate use of these slide patterns when the content supports them:

- "stats" slides — every time the source contains 2+ comparable numbers, render
  them as a stats slide (3–4 KPIs side by side: "47%", "3.2x", "$1.4B").
- Numeric-trend slides — populate the slide content with a `chart` payload:
  `{"chart_type": "bar"|"line"|"pie", "chart_data": [{"label":"Q1","value":12}, ...]}`.
  Use bar for category comparisons, line for time series, pie for share-of-total.
  Include 3–8 data points; only use real numbers from the source.
- Process / flow slides — for any "step 1 → step 2 → step 3" content, output a
  `process_circle` block per step with a single-word label.
- Image placeholders — when a slide would benefit from a visual, add an `image`
  block whose `content` is a SHORT english description (≤8 words) of the image
  to render later (e.g. "skyline of mumbai at night", "doctor reviewing a tablet").
  The frontend will use these descriptions to generate AI images.
- Quote slides — for any pull-quote-worthy sentence in the source, use a "quote"
  slide with the exact text and attribution.
- Timeline slides — chronological bullets with a date prefix.

Keep at least one stats, one chart, and one image-placeholder slide if the
source supports them. Never invent statistics or quotes.
"""


def level_instructions(level: str | None) -> str:
    """Return the level-specific instruction block for prompt rendering."""
    if (level or "simple").lower() == "advanced":
        return _ADVANCED_INSTRUCTIONS
    return _SIMPLE_INSTRUCTIONS


def render(template: Template, **kwargs) -> str:
    return template.substitute(**kwargs)
