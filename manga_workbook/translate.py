"""Offline JA->EN translation via Helsinki-NLP/opus-mt-ja-en (CPU, no API key)."""
import html
import re
from functools import lru_cache

MODEL = "Helsinki-NLP/opus-mt-ja-en"

_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


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
    idx = [i for i, ln in enumerate(lines) if ln]
    out = [""] * len(lines)
    if not idx:
        return out
    results = _pipe()([lines[i] for i in idx], max_length=128)
    for i, r in zip(idx, results):
        out[i] = _clean(r["translation_text"])
    return out
