"""Export a workbook to an Anki deck (.apkg) via genanki.

Vocabulary cards (word -> reading + meaning) and sentence cards (line -> reading
+ English), built from workbook.json so the chapter drops straight into spaced
repetition. Furigana renders as HTML <ruby> in Anki. Stable model/deck/note ids
mean re-exporting a chapter updates the same notes instead of duplicating them.
"""
import hashlib

import genanki


def _id(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


_RUBY_CSS = ".card{text-align:center;font-family:sans-serif} ruby rt{font-size:.5em;color:#666}"

_VOCAB_MODEL = genanki.Model(
    _id("manga-workbook/vocab"), "Manga vocab",
    fields=[{"name": "Word"}, {"name": "Reading"}, {"name": "Meaning"}],
    templates=[{
        "name": "Recall",
        "qfmt": "<div style='font-size:42px'>{{Word}}</div>",
        "afmt": "{{FrontSide}}<hr><div style='font-size:30px'>{{Reading}}</div><div>{{Meaning}}</div>",
    }],
    css=_RUBY_CSS)

_SENT_MODEL = genanki.Model(
    _id("manga-workbook/sentence"), "Manga sentence",
    fields=[{"name": "JA"}, {"name": "Furigana"}, {"name": "EN"}],
    templates=[{
        "name": "Read",
        "qfmt": "<div style='font-size:26px'>{{JA}}</div>",
        "afmt": "{{FrontSide}}<hr><div style='font-size:26px'>{{Furigana}}</div>"
                "<div style='color:#555'>{{EN}}</div>",
    }],
    css=_RUBY_CSS.replace("text-align:center;", ""))


def build_anki(workbook, out_apkg, include_sentences=True) -> int:
    """Write an .apkg for the workbook. Returns the number of notes."""
    chapter = workbook.get("chapter", "chapter")
    deck = genanki.Deck(_id("deck/" + chapter), f"Manga · {chapter}")
    ctag = "manga::" + chapter.replace(" ", "_")
    notes = 0

    sv = workbook.get("summary_vocab", {})
    for cat, items in (("verb", sv.get("verbs", [])), ("noun", sv.get("nouns", [])),
                       ("adj", sv.get("adjectives", []))):
        for v in items:
            if not v.get("en"):
                continue
            deck.add_note(genanki.Note(
                model=_VOCAB_MODEL, fields=[v["word"], v["furigana"], v["en"]],
                tags=[ctag, "pos::" + cat], guid=genanki.guid_for(chapter, "v", v["word"])))
            notes += 1

    if include_sentences:
        seen = set()
        for p in workbook["pages"]:
            for d in p["dialog"]:
                ja = d["plain"]
                if ja in seen:
                    continue
                seen.add(ja)
                deck.add_note(genanki.Note(
                    model=_SENT_MODEL, fields=[ja, d["furigana"], d.get("en", "")],
                    tags=[ctag, "sentence"], guid=genanki.guid_for(chapter, "s", ja)))
                notes += 1

    genanki.Package(deck).write_to_file(str(out_apkg))
    return notes


def _main():
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Export a workbook.json to an Anki .apkg")
    ap.add_argument("workbook_json")
    ap.add_argument("-o", "--out", default="manga.apkg")
    ap.add_argument("--no-sentences", action="store_true", help="vocabulary cards only")
    a = ap.parse_args()
    wb = json.loads(Path(a.workbook_json).read_text(encoding="utf-8"))
    n = build_anki(wb, a.out, include_sentences=not a.no_sentences)
    print(f"wrote {a.out} ({n} notes)")


if __name__ == "__main__":
    _main()
