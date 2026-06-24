"""English analysis via spaCy: tokenization, lemmas, and POS word extraction.

The English counterpart of the old fugashi/unidic backend. Emits the same token
dict shape the rest of the pipeline consumes — ``{s, l, p, p2}`` — minus the
Japanese-only reading field (Latin script has no furigana). Words are categorised
into verbs / nouns / adjectives by spaCy's universal POS tags and reduced to their
dictionary (lemma) form so the vocabulary lists read like a dictionary.
"""
import re
from functools import lru_cache

_nlp = None

# spaCy universal POS (token.pos_) -> workbook category.
POS_MAP = {"VERB": "verbs", "NOUN": "nouns", "ADJ": "adjectives"}

_JUNK = re.compile(r"^[\W\d_]*$")  # all punctuation / digits / underscores -> junk


@lru_cache(maxsize=8192)
def is_real_word(word: str) -> bool:
    """True if the word exists in the English frequency corpus. Comic lettering is
    all-caps, which defeats spaCy's proper-noun detection, so character names
    (Denji, Pochita) and OCR garble (yol, becalse) would otherwise pollute the
    vocab/exercises. A nonzero corpus frequency keeps only real words."""
    from wordfreq import zipf_frequency

    return bool(word) and zipf_frequency(word, "en") > 0


def nlp():
    global _nlp
    if _nlp is None:
        import spacy

        # Only the tagger/lemmatizer are needed; the parser/NER are dead weight.
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    return _nlp


def _is_junk(w: str) -> bool:
    return not w or bool(_JUNK.match(w))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tokens(text: str) -> list:
    """OCR line -> list of {s:surface, l:lemma, p:pos, p2:tag}.
    Used to build offline exercises (base-form, fill-in-the-blank, prepositions)."""
    out = []
    for t in nlp()(text):
        if t.is_space:
            continue
        out.append({
            "s": t.text,
            "l": t.lemma_.lower() or t.text.lower(),
            "p": t.pos_,
            "p2": t.tag_,
        })
    return out


def extract_words(text: str) -> dict:
    """OCR line -> {verbs, nouns, adjectives}, each as lowercase dictionary forms.

    Content words only: stop words, punctuation, numbers and proper nouns are
    dropped, so the vocabulary lists stay study-worthy. Auxiliaries ("is", "have"
    as helpers) are tagged AUX by spaCy and so naturally excluded.
    """
    words = {"verbs": [], "nouns": [], "adjectives": []}
    for t in nlp()(text):
        cat = POS_MAP.get(t.pos_)
        if not cat:
            continue
        if t.is_stop or t.is_punct or not t.is_alpha:
            continue
        lemma = (t.lemma_ or t.text).lower()
        if len(lemma) < 2 or _is_junk(lemma) or not is_real_word(lemma):
            continue
        words[cat].append(lemma)
    return words
