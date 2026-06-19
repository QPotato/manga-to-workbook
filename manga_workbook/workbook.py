"""Assemble the workbook data structure from OCR boxes + cleaned images."""
from collections import Counter

from .exercises import build_exercises
from .language import extract_words, furigana_html, tokens as tokenize


def _dedupe(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_workbook(ordered_files, ocr_pages, cleaned_map, chapter="chapter",
                  translate=True, on_page=None):
    """ordered_files: list of original filenames in page order.
    ocr_pages: {filename: [box,...]}.  cleaned_map: {filename: cleaned_path}.

    Returns dict: {chapter, summary_vocab, pages:[...]}.
    """
    if translate:
        from .translate import translate_lines

    pages = []
    chapter_nouns = Counter()
    chapter_verbs = Counter()
    chapter_adjs = Counter()

    for pi, fname in enumerate(ordered_files, 1):
        boxes = ocr_pages.get(fname, [])
        dialog = []
        verbs, nouns, adjs = [], [], []
        for box in boxes:
            text = box["text"].strip()
            if not text:
                continue
            dialog.append({"plain": text, "furigana": furigana_html(text), "en": "",
                           "tokens": tokenize(text)})
            w = extract_words(text)
            verbs += w["verbs"]
            nouns += w["nouns"]
            adjs += w["adjectives"]
        if translate and dialog:
            for d, en in zip(dialog, translate_lines([d["plain"] for d in dialog])):
                d["en"] = en
        if on_page:
            on_page(pi, len(ordered_files))
        chapter_verbs.update(verbs)
        chapter_nouns.update(nouns)
        chapter_adjs.update(adjs)
        pages.append(
            {
                "filename": fname,
                "cleaned_path": str(cleaned_map.get(fname, "")),
                "header": {
                    "verbs": [furigana_html(w) for w in _dedupe(verbs)],
                    "nouns": [furigana_html(w) for w in _dedupe(nouns)],
                    "adjectives": [furigana_html(w) for w in _dedupe(adjs)],
                },
                "dialog": dialog,
            }
        )

    def enrich(words):
        ens = translate_lines(words) if (translate and words) else [""] * len(words)
        return [
            {"word": w, "furigana": furigana_html(w), "en": en}
            for w, en in zip(words, ens)
        ]

    summary = {
        "verbs": enrich([w for w, _ in chapter_verbs.most_common(20)]),
        "nouns": enrich([w for w, _ in chapter_nouns.most_common(30)]),
        "adjectives": enrich([w for w, _ in chapter_adjs.most_common(20)]),
    }
    wb = {"chapter": chapter, "summary_vocab": summary, "pages": pages}
    wb["exercises"] = build_exercises(wb)
    return wb
