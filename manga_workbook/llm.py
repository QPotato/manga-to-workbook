"""Optional LLM enhancement (Claude vision): correct OCR + translation, write Qs.

Isolated, opt-in stage. The free pipeline (pcleaner + manga-ocr + opus-mt +
fugashi + jamdict) does the heavy lifting; this refines it only when the user
enables the checkbox and supplies an API key. Per CLAUDE.md, free tools first.

Two calls, both using Claude structured outputs (messages.parse) so results are
typed, and both cached into workbook.json so re-renders never re-call the API:
  correct_pages() — per page: the page image + the free-OCR draft -> corrected
    Japanese + natural English per box (vision fixes manga-ocr's stylized-text
    errors that text-only correction could only guess at).
  comprehension()  — per chapter: questions about the story + an answer key.
"""
import base64
import io
from pathlib import Path

from pydantic import BaseModel

# Selectable in the webapp. Opus = best JA OCR/translation; Sonnet = cheaper;
# Haiku = cheapest. Default Opus per Anthropic guidance.
ALLOWED_MODELS = ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5")
DEFAULT_MODEL = "claude-opus-4-8"

_MAX_EDGE = 1600  # downscale the long edge to bound image tokens / cost


class _Box(BaseModel):
    id: int
    text: str   # corrected Japanese as printed ("" if the box isn't real text)
    en: str     # natural English translation ("" for SFX / non-dialogue)


class _Page(BaseModel):
    boxes: list[_Box]


class _QA(BaseModel):
    question: str
    answer: str


class _Questions(BaseModel):
    items: list[_QA]


def _client(api_key=None):
    import anthropic
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def _image_block(path: Path) -> dict:
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > _MAX_EDGE:
            im.thumbnail((_MAX_EDGE, _MAX_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


_CORRECT_SYS = (
    "You are a Japanese manga OCR corrector and translator. You receive a manga "
    "page image and a draft OCR of its text boxes (numbered). For each box return: "
    "the box id; the EXACT Japanese text as printed in the image (fix OCR errors "
    "such as ソ/ツ or 拓/取 and garbled stylized text; keep okurigana and "
    "punctuation); and a natural, concise English translation. For sound effects "
    "or non-dialogue, return the Japanese text with an empty en. Return every "
    "input box id exactly once."
)


def correct_pages(pages, model=DEFAULT_MODEL, api_key=None, on_progress=None):
    """pages: list of (filename, image_path, [{"id","text"}, ...]).
    Returns {filename: {id: {"text", "en"}}}. Pages with no boxes are skipped."""
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {ALLOWED_MODELS}")
    client = _client(api_key)
    out = {}
    total = len(pages)
    for i, (fname, img_path, boxes) in enumerate(pages, 1):
        if boxes:
            draft = "\n".join(f'{b["id"]}: {b["text"]}' for b in boxes)
            msg = client.messages.parse(
                model=model, max_tokens=4096, system=_CORRECT_SYS,
                messages=[{"role": "user", "content": [
                    _image_block(Path(img_path)),
                    {"type": "text", "text": f"Draft OCR boxes:\n{draft}"},
                ]}],
                output_format=_Page,
            )
            out[fname] = {b.id: {"text": b.text, "en": b.en}
                          for b in msg.parsed_output.boxes}
        if on_progress:
            on_progress(i, total)
    return out


_QUESTIONS_SYS = (
    "You are a Japanese-language teacher. Given a manga chapter's dialogue "
    "(Japanese, with English where available), write {n} comprehension questions "
    "in English about what happens, the characters, and their motivations, ordered "
    "easy to hard, each with a short answer. Base answers only on the given text."
)


def comprehension(chapter, lines, model=DEFAULT_MODEL, api_key=None, n=8):
    """lines: list of (ja, en) across the chapter. Returns [{"q","a"}, ...]."""
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {ALLOWED_MODELS}")
    if not lines:
        return []
    client = _client(api_key)
    body = "\n".join(f"- {ja}" + (f"  ({en})" if en else "") for ja, en in lines)
    msg = client.messages.parse(
        model=model, max_tokens=4096, system=_QUESTIONS_SYS.replace("{n}", str(n)),
        messages=[{"role": "user", "content": f"Chapter: {chapter}\n\nDialogue:\n{body}"}],
        output_format=_Questions,
    )
    return [{"q": q.question, "a": q.answer} for q in msg.parsed_output.items]
