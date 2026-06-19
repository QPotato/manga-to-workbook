"""Japanese analysis via fugashi/unidic: furigana HTML + POS word extraction."""
import re
import fugashi

from .furigana import kata_to_hira, split_furigana

_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        _tagger = fugashi.Tagger()
    return _tagger


# unidic pos1 -> workbook category
POS_MAP = {"動詞": "verbs", "名詞": "nouns", "形容詞": "adjectives"}

_JUNK = re.compile(r"^[、。．・…！？!?\s（）()「」『』ー~〜\-—,.\"']*$")


def _is_junk(w: str) -> bool:
    return not w or bool(_JUNK.match(w))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _reading(feat) -> str | None:
    r = getattr(feat, "kana", None) or getattr(feat, "pron", None)
    return kata_to_hira(r) if r else None


def furigana_html(text: str) -> str:
    """OCR line -> HTML with <ruby> over kanji."""
    out = []
    for w in tagger()(text):
        for chunk, ruby in split_furigana(w.surface, _reading(w.feature)):
            if ruby:
                out.append(f"<ruby>{_esc(chunk)}<rt>{_esc(ruby)}</rt></ruby>")
            else:
                out.append(_esc(chunk))
    return "".join(out)


def tokens(text: str) -> list:
    """OCR line -> list of {s:surface, l:lemma, r:reading_hira, p:pos1, p2:pos2}.
    Used to build offline exercises (conjugation, particle blanks, fill-in-the-blank)."""
    out = []
    for w in tagger()(text):
        f = w.feature
        out.append({
            "s": w.surface,
            "l": getattr(f, "lemma", None) or w.surface,
            "r": _reading(f) or "",
            "p": f.pos1,
            "p2": f.pos2,
        })
    return out


def extract_words(text: str) -> dict:
    """OCR line -> {verbs, nouns, adjectives}. Verbs/adjectives as dictionary form."""
    words = {"verbs": [], "nouns": [], "adjectives": []}
    for w in tagger()(text):
        cat = POS_MAP.get(w.feature.pos1)
        if not cat:
            continue
        if cat in ("verbs", "adjectives"):
            word = getattr(w.feature, "lemma", None) or w.surface
        else:  # nouns: surface keeps the form the learner sees
            word = w.surface
        if cat == "nouns" and w.feature.pos2 in ("数詞", "代名詞"):
            continue  # skip numbers / pronouns
        if not _is_junk(word):
            words[cat].append(word)
    return words
