"""Assemble the workbook data structure from OCR boxes + cleaned images."""
from collections import Counter

from .dictionary import gloss as dict_gloss
from .exercises import build_exercises
from .jlpt import label as jlpt_label
from .language import extract_words, furigana_html, tokens as tokenize


# Cap each per-page header word list so text-dense pages (covers, splash pages)
# don't wrap into a tall header that squeezes the panels. The full, frequency-
# ranked vocabulary still appears on the summary page.
HEADER_MAX = 16


def _dedupe(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _make_page(fname, cleaned_path, texts):
    """Build one page from texts = list of (plain, en, ocr_or_None).
    `ocr` is the pre-correction text kept for reference when an LLM rewrote `plain`.
    Stores raw per-page words under `_words` so the summary/exercises can be
    recomputed after an LLM correction pass without re-tokenizing the whole book.
    """
    dialog, verbs, nouns, adjs = [], [], [], []
    for plain, en, ocr in texts:
        plain = plain.strip()
        if not plain:
            continue
        d = {"plain": plain, "furigana": furigana_html(plain), "en": en or "",
             "tokens": tokenize(plain)}
        if ocr is not None and ocr != plain:
            d["ocr"] = ocr  # original OCR, kept when the LLM corrected the line
        dialog.append(d)
        w = extract_words(plain)
        verbs += w["verbs"]
        nouns += w["nouns"]
        adjs += w["adjectives"]
    return {
        "filename": fname,
        "cleaned_path": str(cleaned_path or ""),
        "header": {
            "verbs": [furigana_html(w) for w in _dedupe(verbs)[:HEADER_MAX]],
            "nouns": [furigana_html(w) for w in _dedupe(nouns)[:HEADER_MAX]],
            "adjectives": [furigana_html(w) for w in _dedupe(adjs)[:HEADER_MAX]],
        },
        "_words": {"verbs": verbs, "nouns": nouns, "adjectives": adjs},
        "dialog": dialog,
    }


def _enrich(words, category):
    # Dictionary glosses (offline JMdict), not opus-mt: single words need a
    # dictionary, not a sentence translator. Always on; needs no torch.
    return [
        {"word": w, "furigana": furigana_html(w), "en": dict_gloss(w, category),
         "jlpt": jlpt_label(w)}
        for w in words
    ]


def _finalize(wb):
    """(Re)compute summary vocabulary + exercises from the pages' raw words."""
    cv, cn, ca = Counter(), Counter(), Counter()
    for p in wb["pages"]:
        w = p.get("_words", {})
        cv.update(w.get("verbs", []))
        cn.update(w.get("nouns", []))
        ca.update(w.get("adjectives", []))
    wb["summary_vocab"] = {
        "verbs": _enrich([w for w, _ in cv.most_common(20)], "verbs"),
        "nouns": _enrich([w for w, _ in cn.most_common(30)], "nouns"),
        "adjectives": _enrich([w for w, _ in ca.most_common(20)], "adjectives"),
    }
    wb["exercises"] = build_exercises(wb)
    return wb


def build_workbook(ordered_files, ocr_pages, cleaned_map, chapter="chapter",
                  translate=True, on_page=None):
    """ordered_files: list of original filenames in page order.
    ocr_pages: {filename: [box,...]}.  cleaned_map: {filename: cleaned_path}.

    Returns dict: {chapter, summary_vocab, pages:[...], exercises}.
    """
    if translate:
        from .translate import translate_lines

    pages = []
    for pi, fname in enumerate(ordered_files, 1):
        boxes = ocr_pages.get(fname, [])
        page = _make_page(fname, cleaned_map.get(fname, ""),
                          [(b["text"], "", None) for b in boxes])
        if translate and page["dialog"]:
            ens = translate_lines([d["plain"] for d in page["dialog"]])
            for d, en in zip(page["dialog"], ens):
                d["en"] = en
        if on_page:
            on_page(pi, len(ordered_files))
        pages.append(page)

    return _finalize({"chapter": chapter, "pages": pages})


def apply_corrections(wb, corrections):
    """Replace each page's dialogue with LLM-corrected text + translation, then
    recompute headers/summary/exercises. corrections: {filename: {id: {text, en}}}
    where id is the 1-based index of the line in that page's (free) dialog."""
    new_pages = []
    for p in wb["pages"]:
        fix = corrections.get(p["filename"])
        if not fix:
            new_pages.append(p)
            continue
        texts = []
        for i, d in enumerate(p["dialog"], 1):
            f = fix.get(i)
            if f and f.get("text", "").strip():
                texts.append((f["text"], f.get("en", ""), d["plain"]))
            else:  # no correction for this line -> keep the free version
                texts.append((d["plain"], d.get("en", ""), d.get("ocr")))
        new_pages.append(_make_page(p["filename"], p["cleaned_path"], texts))
    wb["pages"] = new_pages
    return _finalize(wb)
