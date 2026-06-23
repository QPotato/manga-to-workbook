"""One-time builder for the bundled en->es gloss dictionary.

Uses the FreeDict+WikDict ``eng-spa`` TEI source and flattens it to a compact
``manga_workbook/data/en-es.json`` mapping ``headword -> {pos: [spanish, ...]}``,
grouped by part of speech (``v`` verb, ``n`` noun, ``a`` adjective, ``x`` other) so
``dictionary.py`` can return the verb gloss for a verb and the noun gloss for a
noun (e.g. fall -> caer as a verb, not "morir"). FreeDict eng-spa is CC-BY-SA 3.0
(WikDict, from Wiktionary via DBnary).

Usage (TEI already extracted under data/_freedict/):
    python data/build_dict.py data/_freedict/eng-spa/eng-spa.tei

Source: https://download.freedict.org/dictionaries/eng-spa/
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.tei-c.org/ns/1.0}"
MAX_GLOSSES = 6  # per (headword, pos); runtime trims further
OUT = Path(__file__).resolve().parent.parent / "manga_workbook" / "data" / "en-es.json"

# FreeDict <pos> value -> our bucket key. Everything that isn't verb/noun/adj
# (adv, preposition, proper noun, interjection, ...) goes to "x" (fallback pool).
def _poskey(pos_text: str) -> str:
    return {"v": "v", "n": "n", "adj": "a"}.get(pos_text, "x")


def build(tei_path: str) -> dict:
    from wordfreq import zipf_frequency

    root = ET.parse(tei_path).getroot()
    out: dict[str, dict[str, list[str]]] = {}
    for entry in root.iter(f"{NS}entry"):
        orth = entry.find(f"{NS}form/{NS}orth")
        if orth is None or not (orth.text or "").strip():
            continue
        head = orth.text.strip().lower()
        pos = entry.find(f"{NS}gramGrp/{NS}pos")
        key = _poskey((pos.text or "").strip().lower() if pos is not None else "")
        glosses = out.setdefault(head, {}).setdefault(key, [])
        for cit in entry.iter(f"{NS}cit"):
            if cit.get("type") != "trans":
                continue
            for q in cit.iter(f"{NS}quote"):
                g = (q.text or "").strip()
                if g and g.lower() != head and g not in glosses:
                    glosses.append(g)  # collect all; sort/trim after
    # The TEI isn't usefully ordered (house -> "casalicio" before "casa"). Rank each
    # bucket by: single-word glosses first (a learner wants "correr", not the phrase
    # "en marcha"), then Spanish corpus frequency (the common translation leads).
    result = {}
    for head, buckets in out.items():
        nb = {}
        for key, glosses in buckets.items():
            if not glosses:
                continue
            glosses.sort(key=lambda g: (" " not in g, zipf_frequency(g, "es")), reverse=True)
            nb[key] = glosses[:MAX_GLOSSES]
        if nb:
            result[head] = nb
    return result


def main():
    tei = sys.argv[1] if len(sys.argv) > 1 else "data/_freedict/eng-spa/eng-spa.tei"
    data = build(tei)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({len(data)} headwords, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
