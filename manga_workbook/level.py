"""Approximate difficulty band for an English word, from corpus frequency.

There is no free, offline, per-word CEFR list, so we substitute frequency bands
and display them CEFR-style (A1 easiest .. C2 hardest). Frequencies come from
`wordfreq` (Zipf scale: ~7 = "the", ~5 ≈ top-1000, ~3 = uncommon, 0 = unknown).
Approximate — for level filtering/display, not authoritative.
"""
from functools import lru_cache

# Zipf-frequency thresholds -> CEFR-style band. Higher frequency = easier word.
_BANDS = [(5.0, "A1"), (4.5, "A2"), (4.0, "B1"), (3.5, "B2"), (3.0, "C1"), (0.0, "C2")]


@lru_cache(maxsize=8192)
def label(word: str) -> str:
    """CEFR-style band ("A1".."C2") for a word, or "" when frequency is unknown."""
    if not word:
        return ""
    from wordfreq import zipf_frequency

    z = zipf_frequency(word.lower(), "en")
    if z <= 0:
        return ""
    for threshold, band in _BANDS:
        if z >= threshold:
            return band
    return "C2"
