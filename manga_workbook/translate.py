"""Offline JA->EN translation via Helsinki-NLP/opus-mt-ja-en (CPU, no API key)."""
import html
import re
from collections import Counter
from functools import lru_cache

from .dictionary import gloss as _gloss

MODEL = "Helsinki-NLP/opus-mt-ja-en"

_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_JA = re.compile(r"[぀-ヿ㐀-鿿々]")  # hiragana/katakana/kanji/々
_KATA_ONLY = re.compile(r"^[゠-ヿ゠ー・\s]+$")
_STAGE = re.compile(r"^[\(\[][^)\]]*[\)\]]$")  # invented "(Laughter)" / "[Music]"
# opus-mt-ja-en hallucination artifacts: it emits these no matter the input.
_ARTIFACTS = ("hugo barra", "speaking native language", "speaking in foreign language")


def _clean(s: str) -> str:
    # opus-mt sometimes emits stray <i>..</i> markup, often entity-encoded
    # (&lt;i&gt;). Unescape AND strip repeatedly so entity-hidden tags can't
    # survive: each pass unescapes, then drops any tags that surfaced. Loops
    # to a fixed point (handles double-encoding too).
    prev = None
    while prev != s:
        prev = s
        s = _TAG.sub("", html.unescape(s))
    return s.strip()


def _is_sfx(s: str) -> bool:
    # Short katakana-only line JMdict doesn't know -> sound effect (ガーッ, ドォン);
    # opus-mt only hallucinates on these. Real loanwords (ドラゴン) are in JMdict, kept.
    return len(s) <= 4 and bool(_KATA_ONLY.match(s)) and not _gloss(s)


def _translatable(s: str) -> bool:
    # Needs real Japanese; pure punctuation/digits/latin (……, ！？, ＸＸ) and SFX skip.
    return bool(_JA.search(s)) and not _is_sfx(s)


def _collapse_repeats(s: str) -> str:
    # opus-mt loops phrases; drop consecutive duplicate chunks (sentence- or
    # comma-separated) and any single word repeated 3+ times.
    out = []
    for p in re.split(r"(?<=[.!?,])\s+", s):
        key = p.strip().rstrip(",").lower()
        if key and (not out or key != out[-1][1]):
            out.append((p, key))
    return re.sub(r"\b(\w+)( \1\b){2,}", r"\1", " ".join(p for p, _ in out))


def _degenerate(s: str) -> bool:
    # A phrase looped many times ("it's a tree, it's a tree, ...") or output with
    # very low word variety -> the translation failed; better blank than garbage.
    chunks = [c.strip().rstrip(",.!?").lower() for c in re.split(r"[.!?,]\s*", s) if c.strip()]
    if chunks and max(Counter(chunks).values()) >= 5:
        return True
    words = s.split()
    return len(words) >= 12 and len(set(w.lower() for w in words)) / len(words) < 0.45


def _sane(out: str) -> str:
    # Reject degenerate output: known artifacts, invented stage directions, loops.
    if any(a in out.lower() for a in _ARTIFACTS) or _STAGE.match(out.strip()):
        return ""
    if _degenerate(out):
        return ""
    return _collapse_repeats(out).strip()


@lru_cache(maxsize=1)
def _pipe():
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1  # use GPU when present
    return pipeline("translation", model=MODEL, device=device)


def translate_lines(lines):
    """Translate a list of dialogue lines. Returns a list of EN strings (same length).

    Batched in one call so the model sees the page together (better than one-by-one),
    while still mapping each source line to its own translation.
    """
    lines = [ln.strip() for ln in lines]
    idx = [i for i, ln in enumerate(lines) if _translatable(ln)]
    out = [""] * len(lines)
    if not idx:
        return out
    results = _pipe()([lines[i] for i in idx], max_length=128)
    for i, r in zip(idx, results):
        out[i] = _sane(_clean(r["translation_text"]))
    return out
