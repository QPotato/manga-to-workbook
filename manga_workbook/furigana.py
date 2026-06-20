"""Okurigana-aware furigana splitting. Maps a reading onto the kanji core of a token."""
import re

import jaconv

_DIGIT = re.compile(r"[0-9０-９]")


def kata_to_hira(s: str) -> str:
    return jaconv.kata2hira(s)


def has_digit(s: str) -> bool:
    return bool(_DIGIT.search(s))


def is_kanji(ch: str) -> bool:
    return ('一' <= ch <= '鿿') or ch == '々'  # CJK + iteration mark 々


def has_kanji(s: str) -> bool:
    return any(is_kanji(c) for c in s)


def split_furigana(surface: str, reading_hira: str | None):
    """Return list of (text, ruby) tuples. ruby is None for plain kana runs.

    Strips matching leading/trailing kana (okurigana) so the ruby sits only on the
    kanji core. Compounds without okurigana get one ruby over the whole word.
    """
    # Tokens mixing a digit with kanji (１日, ３日) fuse in unidic to a calendar
    # reading (１日 -> ついたち) that is wrong for the usual counter/duration sense.
    # Counter readings are context-dependent and unreliable, so show no furigana
    # rather than a wrong one; the digit itself never needs kana.
    if not has_kanji(surface) or not reading_hira or has_digit(surface):
        return [(surface, None)]

    s, r = surface, reading_hira

    suffix = ""
    while s and r and not is_kanji(s[-1]) and s[-1] == r[-1]:
        suffix = s[-1] + suffix
        s, r = s[:-1], r[:-1]

    prefix = ""
    while s and r and not is_kanji(s[0]) and s[0] == r[0]:
        prefix += s[0]
        s, r = s[1:], r[1:]

    parts = []
    if prefix:
        parts.append((prefix, None))
    if s:
        parts.append((s, r) if has_kanji(s) else (s, None))
    if suffix:
        parts.append((suffix, None))
    return parts
