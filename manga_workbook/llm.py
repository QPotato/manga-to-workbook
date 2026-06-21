"""Optional LLM enhancement via the local Claude Code CLI (`claude -p`).

Runs on the user's local Claude Code login — no API key, local use only. Isolated
and opt-in: the free pipeline (pcleaner + manga-ocr + opus-mt + fugashi + jamdict)
does the heavy lifting; this refines it when the checkbox is on. Per CLAUDE.md,
free tools first.

Two calls, both cached into workbook.json so re-renders never re-invoke claude:
  correct_pages() — per page: Claude reads the page image (Read tool) + the
    free-OCR draft and returns corrected Japanese + a natural English translation
    per box, fixing the stylized-text errors manga-ocr makes.
  comprehension()  — per chapter: questions about the story + an answer key.

Output is requested as plain JSON and parsed here (the CLI has no schema mode).
"""
import json
import os
import re
import shutil
import subprocess

# Webapp dropdown value -> `claude --model` alias (tracks the current release).
ALLOWED_MODELS = ("opus", "sonnet", "haiku")
DEFAULT_MODEL = "sonnet"

_TIMEOUT = 300  # seconds per page / chapter call
_JSON = re.compile(r"(\{.*\}|\[.*\])", re.S)


def _claude_bin():
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` CLI not found on PATH. Install Claude Code and log in.")
    return exe


def _run(prompt, model, allow_read, timeout=_TIMEOUT):
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {ALLOWED_MODELS}")
    args = [_claude_bin(), "-p", "--model", model, "--output-format", "text"]
    if allow_read:
        args += ["--allowedTools", "Read"]  # pre-approve image reads, no prompt
    proc = subprocess.run(args, input=prompt, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed: {(proc.stderr or proc.stdout)[-800:]}")
    return proc.stdout


def _json_obj(text):
    m = _JSON.search(text)
    if not m:
        raise RuntimeError(f"no JSON in claude output: {text[:300]}")
    return json.loads(m.group(1))


_CORRECT = (
    "You are a Japanese manga OCR corrector and translator.\n"
    "Look at the manga page image with the Read tool: {path}\n"
    "Below is a draft OCR of its text boxes as `id: text`. For EACH box return the "
    "id, the exact Japanese text as printed in the image (fix OCR errors such as "
    "ソ/ツ or 拓/取 and garbled stylized text; keep okurigana and punctuation), and a "
    "natural concise English translation (empty string for pure sound effects). "
    "Return EVERY id exactly once.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"boxes":[{{"id":1,"text":"...","en":"..."}}]}}\n\n'
    "Draft OCR boxes:\n{draft}"
)


def correct_pages(pages, model=DEFAULT_MODEL, on_progress=None):
    """pages: list of (filename, image_path, [{"id","text"}, ...]).
    Returns {filename: {id: {"text","en"}}}. Pages with no boxes are skipped."""
    out = {}
    total = len(pages)
    for i, (fname, img_path, boxes) in enumerate(pages, 1):
        if boxes:
            draft = "\n".join(f'{b["id"]}: {b["text"]}' for b in boxes)
            prompt = _CORRECT.format(path=os.path.abspath(img_path), draft=draft)
            data = _json_obj(_run(prompt, model, allow_read=True))
            fixes = {}
            for b in data.get("boxes", []):
                try:
                    fixes[int(b["id"])] = {"text": str(b.get("text", "")),
                                           "en": str(b.get("en", ""))}
                except (KeyError, ValueError, TypeError):
                    continue
            out[fname] = fixes
        if on_progress:
            on_progress(i, total)
    return out


_QUESTIONS = (
    "You are a Japanese-language teacher. Given a manga chapter's dialogue "
    "(Japanese, with English where available), write {n} comprehension questions "
    "in English about what happens, the characters, and their motivations, ordered "
    "easy to hard, each with a short answer. Base answers only on the given text.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"items":[{{"question":"...","answer":"..."}}]}}\n\n'
    "Chapter: {chapter}\nDialogue:\n{body}"
)


def comprehension(chapter, lines, model=DEFAULT_MODEL, n=8):
    """lines: list of (ja, en) across the chapter. Returns [{"q","a"}, ...]."""
    if not lines:
        return []
    body = "\n".join(f"- {ja}" + (f"  ({en})" if en else "") for ja, en in lines)
    data = _json_obj(_run(_QUESTIONS.format(n=n, chapter=chapter, body=body),
                          model, allow_read=False))
    return [{"q": str(q.get("question", "")), "a": str(q.get("answer", ""))}
            for q in data.get("items", [])]


_GRAMMAR = (
    "You are a Japanese teacher. From the chapter's dialogue, pick the {n} most "
    "useful grammar points for a learner (particles, verb/adjective forms, set "
    "patterns). For each give: the point (e.g. 〜ている), a one-line English "
    "explanation, and one example sentence taken from the dialogue.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"items":[{{"point":"...","explain":"...","example":"..."}}]}}\n\n'
    "Chapter: {chapter}\nDialogue:\n{body}"
)


def grammar(chapter, lines, model=DEFAULT_MODEL, n=6):
    """lines: list of (ja, en). Returns [{"point","explain","example"}, ...]."""
    if not lines:
        return []
    body = "\n".join(f"- {ja}" for ja, _ in lines)
    data = _json_obj(_run(_GRAMMAR.format(n=n, chapter=chapter, body=body),
                          model, allow_read=False))
    return [{"point": str(q.get("point", "")), "explain": str(q.get("explain", "")),
             "example": str(q.get("example", ""))} for q in data.get("items", [])]
