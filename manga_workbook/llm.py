"""Optional LLM enhancement (English -> Spanish). Two providers:

  * DeepSeek API (default) — text-only (no vision). Uses the key in env
    DEEPSEEK_API_KEY or a `DEEPSEEK_API_KEY` file in the project root. It refines
    the rough opus-mt Spanish into natural translations, lightly fixes obvious
    English OCR typos from context, and writes comprehension questions + grammar
    notes in Spanish.
  * Claude Code CLI (`claude -p`) — local login, has vision via the Read tool, so
    it can also correct the English OCR text against the page image.

Both are opt-in and cached into workbook.json so re-renders never re-call them.
Output is requested as plain JSON and parsed here.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# Model menu (webapp dropdown / CLI --model). DeepSeek first => default.
DEEPSEEK_MODELS = ("deepseek-chat", "deepseek-reasoner")
CLAUDE_MODELS = ("opus", "sonnet", "haiku")
ALLOWED_MODELS = DEEPSEEK_MODELS + CLAUDE_MODELS
DEFAULT_MODEL = "deepseek-chat"

_TIMEOUT = 300  # seconds per page / chapter call
_NET_RETRIES = 3  # transient network failures (timeouts, dropped connections)
_JSON = re.compile(r"(\{.*\}|\[.*\])", re.S)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _is_deepseek(model):
    return model in DEEPSEEK_MODELS


# --- DeepSeek (OpenAI-compatible HTTP API) -------------------------------------

def _deepseek_key():
    """Read the key from $DEEPSEEK_API_KEY, else a DEEPSEEK_API_KEY file in the
    project root or CWD. The file holds just the raw `sk-...` key."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key and key.strip():
        return key.strip()
    candidates = [
        Path(__file__).resolve().parent.parent / "DEEPSEEK_API_KEY",  # project root
        Path.cwd() / "DEEPSEEK_API_KEY",
    ]
    for p in candidates:
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            # tolerate a `DEEPSEEK_API_KEY=sk-...` line too
            return text.split("=", 1)[1].strip() if text.startswith("DEEPSEEK_API_KEY=") else text
    raise RuntimeError(
        "DeepSeek API key not found. Set $DEEPSEEK_API_KEY or put it in a "
        "DEEPSEEK_API_KEY file in the project root."
    )


def _deepseek_chat(prompt, model, timeout=_TIMEOUT):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.3,  # translation/Q&A: favor consistency
        # All our prompts request JSON; this makes DeepSeek emit a single valid
        # JSON object instead of occasionally fenced/truncated text.
        "response_format": {"type": "json_object"},
        "max_tokens": 8192,  # avoid truncating long per-page box lists mid-JSON
    }).encode("utf-8")
    req = urllib.request.Request(
        _DEEPSEEK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_deepseek_key()}"},
    )
    # Retry transient network failures (read timeouts, dropped connections). All
    # failures end as RuntimeError so callers can skip a page instead of crashing.
    last = None
    for attempt in range(1, _NET_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"DeepSeek API error {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as e:
            last = e
            time.sleep(2 * attempt)  # brief backoff before retrying
    raise RuntimeError(f"DeepSeek network error after {_NET_RETRIES} attempts: {last}")


# --- Claude Code CLI -----------------------------------------------------------

def _claude_bin():
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` CLI not found on PATH. Install Claude Code and log in.")
    return exe


def _claude_run(prompt, model, allow_read, timeout=_TIMEOUT):
    args = [_claude_bin(), "-p", "--model", model, "--output-format", "text"]
    if allow_read:
        args += ["--allowedTools", "Read"]  # pre-approve image reads, no prompt
    proc = subprocess.run(args, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed: {(proc.stderr or proc.stdout)[-800:]}")
    return proc.stdout


def _run(prompt, model, allow_read, timeout=_TIMEOUT):
    """Dispatch a text prompt to the selected provider. allow_read (image access)
    applies only to Claude; DeepSeek is text-only and ignores it."""
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {ALLOWED_MODELS}")
    if _is_deepseek(model):
        return _deepseek_chat(prompt, model, timeout)
    return _claude_run(prompt, model, allow_read, timeout)


def _json_obj(text):
    m = _JSON.search(text)
    if not m:
        raise ValueError(f"no JSON in LLM output: {text[:300]}")
    return json.loads(m.group(1))  # raises json.JSONDecodeError on malformed JSON


_JSON_RETRIES = 3  # LLMs occasionally emit malformed/fenced JSON; re-ask a few times


def _run_json(prompt, model, allow_read, timeout=_TIMEOUT):
    """Call the LLM and parse its reply as JSON, retrying the whole call when the
    reply isn't valid JSON (DeepSeek in particular sometimes breaks the format).
    Re-raises the last parse error after _JSON_RETRIES attempts."""
    last = None
    for attempt in range(1, _JSON_RETRIES + 1):
        text = _run(prompt, model, allow_read, timeout)
        try:
            return _json_obj(text)
        except (ValueError, json.JSONDecodeError) as e:  # JSONDecodeError subclasses ValueError
            last = e
    raise RuntimeError(
        f"LLM returned no valid JSON after {_JSON_RETRIES} attempts: {last}"
    )


# --- OCR correction / translation ----------------------------------------------

# Claude (vision): fix the English OCR text from the page image AND translate to ES.
_CORRECT_CLAUDE = (
    "You are an English comic OCR corrector and English-to-Spanish translator.\n"
    "Look at the comic page image with the Read tool: {path}\n"
    "Below is a draft OCR of its text boxes as `id: text`. For EACH box return the "
    "id, the exact English text as printed in the image (fix OCR errors such as "
    "l/I, rn/m, 0/O and garbled stylized lettering; keep punctuation), and a "
    "natural concise Spanish translation (empty string for pure sound effects). "
    "Return EVERY id exactly once.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"boxes":[{{"id":1,"text":"...","es":"..."}}]}}\n\n'
    "Draft OCR boxes:\n{draft}"
)

# DeepSeek (text-only): lightly fix obvious English OCR typos and translate to ES.
_TRANSLATE_DEEPSEEK = (
    "You are an English-to-Spanish comic translator. Below are a comic page's text "
    "boxes as `id: english`, in reading order. For EACH box return its id, a cleaned "
    "`text` (fix only obvious OCR typos you can infer from context; otherwise keep "
    "it verbatim), and a natural, concise Spanish translation `es` that reads well in "
    "context (use an empty string for pure sound effects/onomatopoeia). "
    "Return EVERY id exactly once.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"boxes":[{{"id":1,"text":"...","es":"..."}}]}}\n\n'
    "Text boxes:\n{draft}"
)


def correct_pages(pages, model=DEFAULT_MODEL, on_progress=None):
    """pages: list of (filename, image_path, [{"id","text"}, ...]).
    Returns {filename: {id: {"text","es"}}}. Pages with no boxes are skipped.

    Claude reads the image and may rewrite the English `text`. DeepSeek is
    text-only: it lightly fixes obvious typos and produces the Spanish `es`."""
    deepseek = _is_deepseek(model)
    out = {}
    total = len(pages)
    for i, (fname, img_path, boxes) in enumerate(pages, 1):
        if boxes:
            draft = "\n".join(f'{b["id"]}: {b["text"]}' for b in boxes)
            # A single page that the LLM can't return valid JSON for must not abort
            # the whole book: skip it (keep the original OCR + opus-mt ES) and go on.
            originals = {b["id"]: b["text"] for b in boxes}
            try:
                if deepseek:
                    prompt = _TRANSLATE_DEEPSEEK.format(draft=draft)
                    data = _run_json(prompt, model, allow_read=False)
                else:
                    prompt = _CORRECT_CLAUDE.format(path=os.path.abspath(img_path), draft=draft)
                    data = _run_json(prompt, model, allow_read=True)
                fixes = {}
                for b in data.get("boxes", []):
                    try:
                        bid = int(b["id"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    # Fall back to the original OCR text when the LLM omits/blanks it.
                    text = str(b.get("text", "")).strip() or originals.get(bid, "")
                    fixes[bid] = {"text": text, "es": str(b.get("es", ""))}
            except RuntimeError as e:
                print(f"  LLM correction failed for {fname}, keeping original: {e}")
                fixes = {}
            out[fname] = fixes
        if on_progress:
            on_progress(i, total)
    return out


# --- Comprehension questions (in Spanish) --------------------------------------

_QUESTIONS = (
    "You are an English teacher for Spanish-speaking students. Given an English "
    "comic chapter's dialogue (with a Spanish gloss where available), write {n} "
    "comprehension questions about what happens, the characters, and their "
    "motivations, ordered easy to hard, each with a short answer. Write BOTH the "
    "questions AND the answers in SPANISH. Base answers only on the given text.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"items":[{{"question":"...","answer":"..."}}]}}\n\n'
    "Chapter: {chapter}\nDialogue:\n{body}"
)


def comprehension(chapter, lines, model=DEFAULT_MODEL, n=8):
    """lines: list of (text_en, es) across the chapter. Returns [{"q","a"}, ...]
    with both question and answer in Spanish."""
    if not lines:
        return []
    body = "\n".join(f"- {en}" + (f"  ({es})" if es else "") for en, es in lines)
    data = _run_json(_QUESTIONS.format(n=n, chapter=chapter, body=body),
                     model, allow_read=False)
    return [{"q": str(q.get("question", "")), "a": str(q.get("answer", ""))}
            for q in data.get("items", [])]


_GRAMMAR = (
    "You are an English teacher for Spanish-speaking students. From the chapter's "
    "English dialogue, pick the {n} most useful English grammar points for a learner "
    "(verb tenses, phrasal verbs, prepositions, set patterns). For each give: the "
    "point (e.g. present perfect), a one-line explanation IN SPANISH, and one example "
    "sentence taken from the dialogue.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"items":[{{"point":"...","explain":"...","example":"..."}}]}}\n\n'
    "Chapter: {chapter}\nDialogue:\n{body}"
)


def grammar(chapter, lines, model=DEFAULT_MODEL, n=6):
    """lines: list of (text_en, es). Returns [{"point","explain","example"}, ...]."""
    if not lines:
        return []
    body = "\n".join(f"- {en}" for en, _ in lines)
    data = _run_json(_GRAMMAR.format(n=n, chapter=chapter, body=body),
                     model, allow_read=False)
    return [{"point": str(q.get("point", "")), "explain": str(q.get("explain", "")),
             "example": str(q.get("example", ""))} for q in data.get("items", [])]
