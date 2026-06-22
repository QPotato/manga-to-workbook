"""Optional LLM enhancement. Two providers:

  * DeepSeek API (default) — text-only (no vision). Uses the key in env
    DEEPSEEK_API_KEY or a `DEEPSEEK_API_KEY` file in the project root. It refines
    the rough opus-mt English into natural translations and writes comprehension
    questions + grammar notes. It does NOT change the OCR'd Japanese (it can't see
    the page).
  * Claude Code CLI (`claude -p`) — local login, has vision via the Read tool, so
    it can also correct the Japanese OCR text from the page image.

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

# Claude (vision): fix the Japanese OCR text from the page image AND translate.
_CORRECT_CLAUDE = (
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

# DeepSeek (text-only): keep the Japanese as-is, just produce natural English.
_TRANSLATE_DEEPSEEK = (
    "You are a Japanese-to-English manga translator. Below are a manga page's text "
    "boxes as `id: japanese`, in reading order. For EACH box return its id and a "
    "natural, concise English translation that reads well in context (use an empty "
    "string for pure sound effects/onomatopoeia). Do NOT change the Japanese. "
    "Return EVERY id exactly once.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"boxes":[{{"id":1,"en":"..."}}]}}\n\n'
    "Text boxes:\n{draft}"
)


def correct_pages(pages, model=DEFAULT_MODEL, on_progress=None):
    """pages: list of (filename, image_path, [{"id","text"}, ...]).
    Returns {filename: {id: {"text","en"}}}. Pages with no boxes are skipped.

    Claude reads the image and may rewrite the Japanese `text`. DeepSeek is
    text-only: it keeps the original Japanese and only improves the `en`."""
    deepseek = _is_deepseek(model)
    out = {}
    total = len(pages)
    for i, (fname, img_path, boxes) in enumerate(pages, 1):
        if boxes:
            draft = "\n".join(f'{b["id"]}: {b["text"]}' for b in boxes)
            # A single page that the LLM can't return valid JSON for must not abort
            # the whole book: skip it (keep the original OCR + opus-mt EN) and go on.
            try:
                if deepseek:
                    prompt = _TRANSLATE_DEEPSEEK.format(draft=draft)
                    data = _run_json(prompt, model, allow_read=False)
                    originals = {b["id"]: b["text"] for b in boxes}
                    fixes = {}
                    for b in data.get("boxes", []):
                        try:
                            bid = int(b["id"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        # keep the OCR Japanese unchanged; only the translation is new
                        fixes[bid] = {"text": originals.get(bid, ""), "en": str(b.get("en", ""))}
                else:
                    prompt = _CORRECT_CLAUDE.format(path=os.path.abspath(img_path), draft=draft)
                    data = _run_json(prompt, model, allow_read=True)
                    fixes = {}
                    for b in data.get("boxes", []):
                        try:
                            fixes[int(b["id"])] = {"text": str(b.get("text", "")),
                                                   "en": str(b.get("en", ""))}
                        except (KeyError, ValueError, TypeError):
                            continue
            except RuntimeError as e:
                print(f"  LLM correction failed for {fname}, keeping original: {e}")
                fixes = {}
            out[fname] = fixes
        if on_progress:
            on_progress(i, total)
    return out


# --- Comprehension questions (in Japanese) -------------------------------------

_QUESTIONS = (
    "You are a Japanese-language teacher. Given a manga chapter's dialogue "
    "(Japanese, with English where available), write {n} comprehension questions "
    "about what happens, the characters, and their motivations, ordered easy to "
    "hard, each with a short answer. Write BOTH the questions AND the answers in "
    "JAPANESE. Base answers only on the given text.\n"
    'Output ONLY JSON, no prose, no markdown fences: '
    '{{"items":[{{"question":"...","answer":"..."}}]}}\n\n'
    "Chapter: {chapter}\nDialogue:\n{body}"
)


def comprehension(chapter, lines, model=DEFAULT_MODEL, n=8):
    """lines: list of (ja, en) across the chapter. Returns [{"q","a"}, ...]
    with both question and answer in Japanese."""
    if not lines:
        return []
    body = "\n".join(f"- {ja}" + (f"  ({en})" if en else "") for ja, en in lines)
    data = _run_json(_QUESTIONS.format(n=n, chapter=chapter, body=body),
                     model, allow_read=False)
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
    data = _run_json(_GRAMMAR.format(n=n, chapter=chapter, body=body),
                     model, allow_read=False)
    return [{"point": str(q.get("point", "")), "explain": str(q.get("explain", "")),
             "example": str(q.get("example", ""))} for q in data.get("items", [])]
