"""Approximate JLPT level for a word, from KanjiDic2 (via jamdict).

KanjiDic2 stores the pre-2010 JLPT level (1-4, where 4 is easiest) per kanji. We
remap it to the modern N5-N1 scale and take a word's level as that of its hardest
kanji; kana-only words default to N5. N3 can't be distinguished from the old
data, so it never appears. Approximate — for level filtering/display, not
authoritative.
"""
from functools import lru_cache

# old KanjiDic2 jlpt (1-4) -> modern N-number; N3 not recoverable from old data
_OLD2N = {4: 5, 3: 4, 2: 2, 1: 1}

_jam = None


def _j():
    global _jam
    if _jam is None:
        from jamdict import Jamdict
        _jam = Jamdict()
    return _jam


def _is_kanji(c: str) -> bool:
    return ("一" <= c <= "鿿") or c == "々"


@lru_cache(maxsize=8192)
def kanji_level(ch: str):
    """Modern N-number (5..1) for a single kanji, or None if unknown."""
    try:
        res = _j().lookup(ch)
    except Exception:
        return None
    if not res.chars:
        return None
    old = getattr(res.chars[0], "jlpt", None)  # KanjiDic2 returns it as a string
    try:
        return _OLD2N.get(int(old))
    except (TypeError, ValueError):
        return None


def word_level(word: str):
    """N-number for a word (its hardest constituent kanji; kana-only -> 5), or None."""
    levels = [lv for lv in (kanji_level(c) for c in word if _is_kanji(c)) if lv]
    if not levels:
        return 5 if word else None     # no kanji -> kana-only -> N5
    return min(levels)                 # lower number = harder


def label(word: str) -> str:
    n = word_level(word)
    return f"N{n}" if n else ""
