"""Assemble the workbook data structure from OCR boxes + cleaned images.

Data model (en->es): each dialog line is {text: <English>, es: <Spanish>, tokens,
ocr?}; each vocab entry is {word: <English>, es: <Spanish gloss>, level: <band>}.
"""
from collections import Counter

from .dictionary import gloss as dict_gloss
from .exercises import build_exercises
from .level import label as level_label
from .language import extract_words, tokens as tokenize


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
    """Build one page from texts = list of (text, es, ocr_or_None).
    `ocr` is the pre-correction text kept for reference when an LLM rewrote `text`.
    Stores raw per-page words under `_words` so the summary/exercises can be
    recomputed after an LLM correction pass without re-tokenizing the whole book.
    """
    dialog, verbs, nouns, adjs = [], [], [], []
    for text, es, ocr in texts:
        text = text.strip()
        if not text:
            continue
        d = {"text": text, "es": es or "", "tokens": tokenize(text)}
        if ocr is not None and ocr != text:
            d["ocr"] = ocr  # original OCR, kept when the LLM corrected the line
        dialog.append(d)
        w = extract_words(text)
        verbs += w["verbs"]
        nouns += w["nouns"]
        adjs += w["adjectives"]
    return {
        "filename": fname,
        "cleaned_path": str(cleaned_path or ""),
        "header": {
            "verbs": _dedupe(verbs)[:HEADER_MAX],
            "nouns": _dedupe(nouns)[:HEADER_MAX],
            "adjectives": _dedupe(adjs)[:HEADER_MAX],
        },
        "_words": {"verbs": verbs, "nouns": nouns, "adjectives": adjs},
        "dialog": dialog,
    }


def _enrich(words, category):
    # Dictionary glosses (offline FreeDict en->es), not opus-mt: single words need
    # a dictionary, not a sentence translator. Always on; needs no torch.
    return [
        {"word": w, "es": dict_gloss(w, category), "level": level_label(w)}
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
                  translate=True, translate_fn=None, on_page=None):
    """ordered_files: list of original filenames in page order.
    ocr_pages: {filename: [box,...]}.  cleaned_map: {filename: cleaned_path}.

    translate_fn(lines)->[es,...] supplies the translator; defaults to offline
    opus-mt when `translate` is set. Pass another (e.g. qwen_ocr.translate_lines)
    to translate with a different engine.

    Returns dict: {chapter, summary_vocab, pages:[...], exercises}.
    """
    if translate_fn is None and translate:
        from .translate import translate_lines
        translate_fn = translate_lines

    pages = []
    for pi, fname in enumerate(ordered_files, 1):
        boxes = ocr_pages.get(fname, [])
        page = _make_page(fname, cleaned_map.get(fname, ""),
                          [(b["text"], "", None) for b in boxes])
        if translate_fn and page["dialog"]:
            ess = translate_fn([d["text"] for d in page["dialog"]])
            for d, es in zip(page["dialog"], ess):
                d["es"] = es
        if on_page:
            on_page(pi, len(ordered_files))
        pages.append(page)

    return _finalize({"chapter": chapter, "pages": pages})


def apply_corrections(wb, corrections):
    """Replace each page's dialogue with LLM-corrected text + translation, then
    recompute headers/summary/exercises. corrections: {filename: {id: {text, es}}}
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
                texts.append((f["text"], f.get("es", ""), d["text"]))
            else:  # no correction for this line -> keep the free version
                texts.append((d["text"], d.get("es", ""), d.get("ocr")))
        new_pages.append(_make_page(p["filename"], p["cleaned_path"], texts))
    wb["pages"] = new_pages
    return _finalize(wb)
