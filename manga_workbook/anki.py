"""Export a workbook to an Anki deck (.apkg) via genanki.

Vocabulary cards (English word -> Spanish meaning) and sentence cards (English line
-> Spanish translation), built from workbook.json so the chapter drops straight into
spaced repetition. Stable model/deck/note ids mean re-exporting a chapter updates
the same notes instead of duplicating them.
"""
import hashlib

import genanki


def _id(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


_CSS = ".card{text-align:center;font-family:sans-serif} .gloss{color:#666}"

_VOCAB_MODEL = genanki.Model(
    _id("comic-workbook/en-es-vocab"), "Comic vocab (en-es)",
    fields=[{"name": "Word"}, {"name": "Meaning"}],
    templates=[{
        "name": "Recall",
        "qfmt": "<div style='font-size:42px'>{{Word}}</div>",
        "afmt": "{{FrontSide}}<hr><div class='gloss' style='font-size:28px'>{{Meaning}}</div>",
    }],
    css=_CSS)

_SENT_MODEL = genanki.Model(
    _id("comic-workbook/en-es-sentence"), "Comic sentence (en-es)",
    fields=[{"name": "EN"}, {"name": "ES"}],
    templates=[{
        "name": "Read",
        "qfmt": "<div style='font-size:24px'>{{EN}}</div>",
        "afmt": "{{FrontSide}}<hr><div class='gloss' style='font-size:22px'>{{ES}}</div>",
    }],
    css=_CSS.replace("text-align:center;", ""))


def build_anki(workbook, out_apkg, include_sentences=True) -> int:
    """Write an .apkg for the workbook. Returns the number of notes."""
    chapter = workbook.get("chapter", "chapter")
    deck = genanki.Deck(_id("deck/" + chapter), f"English · {chapter}")
    ctag = "comic::" + chapter.replace(" ", "_")
    notes = 0

    sv = workbook.get("summary_vocab", {})
    for cat, items in (("verb", sv.get("verbs", [])), ("noun", sv.get("nouns", [])),
                       ("adj", sv.get("adjectives", []))):
        for v in items:
            if not v.get("es"):
                continue
            tags = [ctag, "pos::" + cat]
            if v.get("level"):
                tags.append("level::" + v["level"])
            deck.add_note(genanki.Note(
                model=_VOCAB_MODEL, fields=[v["word"], v["es"]],
                tags=tags, guid=genanki.guid_for(chapter, "v", v["word"])))
            notes += 1

    if include_sentences:
        seen = set()
        for p in workbook["pages"]:
            for d in p["dialog"]:
                en = d["text"]
                if en in seen:
                    continue
                seen.add(en)
                deck.add_note(genanki.Note(
                    model=_SENT_MODEL, fields=[en, d.get("es", "")],
                    tags=[ctag, "sentence"], guid=genanki.guid_for(chapter, "s", en)))
                notes += 1

    genanki.Package(deck).write_to_file(str(out_apkg))
    return notes


def _main():
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Export a workbook.json to an Anki .apkg")
    ap.add_argument("workbook_json")
    ap.add_argument("-o", "--out", default="comic.apkg")
    ap.add_argument("--no-sentences", action="store_true", help="vocabulary cards only")
    a = ap.parse_args()
    wb = json.loads(Path(a.workbook_json).read_text(encoding="utf-8"))
    n = build_anki(wb, a.out, include_sentences=not a.no_sentences)
    print(f"wrote {a.out} ({n} notes)")


if __name__ == "__main__":
    _main()
