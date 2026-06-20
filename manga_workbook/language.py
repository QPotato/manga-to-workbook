"""Japanese analysis via fugashi/unidic: furigana HTML + POS word extraction."""
import re
import fugashi

from .dictionary import gloss
from .furigana import is_kanji, is_katakana_word, kata_to_hira, split_furigana

_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        _tagger = fugashi.Tagger()
    return _tagger


# unidic pos1 -> workbook category
POS_MAP = {"動詞": "verbs", "名詞": "nouns", "形容詞": "adjectives"}

# Grammaticalized verbs that are really compound particles, not study verbs:
# によって / による tokenize as the verb 因る (よる). Drop them from the lists.
VERB_STOPLIST = {"因る", "由る"}

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


def _bad_noun(word: str) -> bool:
    # Single-kanji noun absent from JMdict = bound morpheme / OCR fragment (滅),
    # not a real word. Real single-kanji nouns (国, 王) are in JMdict and kept.
    return len(word) == 1 and is_kanji(word) and not gloss(word)


def extract_words(text: str) -> dict:
    """OCR line -> {verbs, nouns, adjectives}. Verbs/adjectives as dictionary form."""
    words = {"verbs": [], "nouns": [], "adjectives": []}
    toks = list(tagger()(text))
    i = 0
    while i < len(toks):
        w = toks[i]
        f = w.feature
        # Merge a run of katakana noun tokens when unidic over-split a real
        # loanword (アイス+クリーム -> アイスクリーム). Only if the merged form is
        # a JMdict word, so valid split compounds (デビル+ハンター) stay split.
        if f.pos1 == "名詞" and is_katakana_word(w.surface):
            j = i
            while j < len(toks) and toks[j].feature.pos1 == "名詞" \
                    and is_katakana_word(toks[j].surface):
                j += 1
            if j - i > 1:
                merged = "".join(t.surface for t in toks[i:j])
                if gloss(merged):
                    if not _is_junk(merged):
                        words["nouns"].append(merged)
                    i = j
                    continue
        cat = POS_MAP.get(f.pos1)
        if cat:
            if cat == "nouns":
                word = w.surface  # surface keeps the form the learner sees
                if f.pos2 in ("数詞", "代名詞") or _bad_noun(word):
                    i += 1
                    continue
            else:  # verbs / adjectives: dictionary form
                word = getattr(f, "lemma", None) or w.surface
                if cat == "verbs" and word in VERB_STOPLIST:
                    i += 1
                    continue
            if not _is_junk(word):
                words[cat].append(word)
        i += 1
    return words
