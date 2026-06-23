"""Offline EN->ES dictionary glosses from the bundled FreeDict+WikDict eng-spa data.

Used for vocabulary lists / the answer key. opus-mt is a *sentence* translator, so
single dictionary words come out as sentence-like nonsense; a real bilingual
dictionary returns proper glosses instead. The data is flattened to
``data/en-es.json`` (``headword -> {pos: [spanish, ...]}``, grouped by part of
speech and pre-sorted by Spanish frequency) by ``data/build_dict.py``, so a verb
gets its verb gloss and a noun its noun gloss. A lookup miss returns "" so the
workbook shows nothing rather than a confidently-wrong gloss.
"""
import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "en-es.json"
_dict = None

# workbook category -> POS bucket key in the data file.
_CAT2POS = {"verbs": "v", "nouns": "n", "adjectives": "a"}
_POS_ORDER = ("v", "n", "a", "x")  # fallback merge order when the POS is absent


def _load() -> dict:
    global _dict
    if _dict is None:
        try:
            _dict = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Build it once with: python data/build_dict.py <eng-spa.tei>
            _dict = {}
    return _dict


@lru_cache(maxsize=8192)
def gloss(word: str, category: str | None = None, max_glosses: int = 3) -> str:
    """Short Spanish gloss for an English word, or "" if the dictionary lacks it.

    ``category`` ("verbs"/"nouns"/"adjectives") selects the matching part-of-speech
    sense; when it is absent or empty for the word, all senses are merged (the
    requested POS first) so a gloss is still returned.
    """
    if not word:
        return ""
    entry = _load().get(word.lower())
    if not entry:
        return ""
    if isinstance(entry, list):  # tolerate the old flat schema
        entry = {"x": entry}
    key = _CAT2POS.get(category or "")
    if key and entry.get(key):
        senses = entry[key]
    else:  # merge all buckets, requested POS first, de-duped
        seen, senses = set(), []
        for k in ([key] if key else []) + [k for k in _POS_ORDER if k != key]:
            for g in entry.get(k, []):
                if g not in seen:
                    seen.add(g)
                    senses.append(g)
    return "; ".join(senses[:max_glosses])
