"""Offline JA->EN dictionary glosses via jamdict (JMdict).

Used for vocabulary lists / the answer key. opus-mt is a *sentence* translator,
so single dictionary words came out as sentence-like nonsense (茸 -> "I'll take
care of it", スライム -> "Slide", 内臓 -> "Immaculate"). jamdict returns real
dictionary glosses instead. A lookup miss returns "" so the workbook shows
nothing rather than a confidently-wrong gloss.
"""
from functools import lru_cache

_jam = None

# workbook category -> substring expected in a JMdict sense's part-of-speech,
# so e.g. 円 (noun) prefers the "yen" sense over a verb homograph.
_POS_KEYWORD = {"verbs": "verb", "adjectives": "adjective", "nouns": "noun"}


def _jamdict():
    global _jam
    if _jam is None:
        from jamdict import Jamdict
        _jam = Jamdict()
    return _jam


def _senses(entries, keyword):
    """All senses across entries, POS-matching ones first."""
    pref, rest = [], []
    for e in entries:
        for s in e.senses:
            match = keyword and any(keyword in p for p in s.pos)
            (pref if match else rest).append(s)
    return pref + rest


@lru_cache(maxsize=8192)
def gloss(word: str, category: str | None = None, max_glosses: int = 3) -> str:
    """Short EN gloss for a dictionary word, or "" if JMdict has no exact entry."""
    if not word:
        return ""
    try:
        res = _jamdict().lookup(word, strict_lookup=True)  # exact kanji/kana match
    except Exception:
        return ""
    if not res.entries:
        return ""
    keyword = _POS_KEYWORD.get(category or "")
    for s in _senses(res.entries, keyword):
        texts = [g.text for g in s.gloss if g.text]
        if texts:
            return "; ".join(texts[:max_glosses])
    return ""
