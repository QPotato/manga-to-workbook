# Language port — adapt the tool to non-Japanese pairs (side-project)

**Status:** planned side-project, to be done on a **separate worktree** by another
agent. The Japanese version stays the main goal; this is a parallel track.

**Why:** the maintainer knows en/de/es well, so building those pairs yields
faster, higher-quality feedback on layout, exercise design, difficulty
calibration, and the read→write→advance UX — all language-agnostic — which feeds
straight back into the Japanese version.

**Scope:** language pairs like en↔de, es↔en, en↔es. Produce the same outputs
(PDF workbook, HTML reader, Anki deck, exercises, comprehension/grammar). Writing
practice degrades from stroke-order validation to **shadow/copy writing** (Latin
scripts have no stroke order) — see Writing below.

---

## Architecture: what moves, what doesn't

The codebase already splits cleanly around a stable `workbook.json` data model.

### Reusable unchanged (language-neutral)
- `render.py` — PDF.
- `reader.py` — HTML reader (furigana toggle becomes a no-op / hidden for Latin).
- `anki.py` — Anki export.
- `pipeline.py` — orchestration.
- `pcleaner_runner.py` **cleaning** — see Cleaning below (mostly portable).
- `llm.py` — the `claude -p` OCR-correct / translate / grammar / comprehension
  calls work for en/de/es out of the box (often better than JP). Trim the
  JP-specific hallucination guards (katakana-SFX skip) in any non-LLM path.

### JP-bound — must swap (concentrated here)
| file | now (JP) | replace with |
|---|---|---|
| `language.py` | fugashi/unidic (tokenize, POS, lemma, reading) | **spaCy** (`en_core_web_sm`, `de_core_news_sm`, `es_core_news_sm`) emitting the **same token dict** `{s:surface, l:lemma, r:reading, p:pos1, p2:pos2}` (reading = "" for Latin). Map spaCy POS → verb/noun/adj categories. |
| `translate.py` | `Helsinki-NLP/opus-mt-ja-en` | swap the model id to the pair (`opus-mt-en-de`, `de-en`, `en-es`, `es-en` all exist). Keep the `_clean`/repeat-collapse logic; drop katakana/SFX guards. |
| `dictionary.py` | `jamdict` (JMdict) | bilingual dict for the pair (FreeDict / Wiktextract — see Data), or fall back to opus-mt / `claude -p` for single-word glosses. |
| OCR (via `pcleaner_runner.ocr_dir`) | `manga-ocr` (JP only) | PaddleOCR / EasyOCR / Tesseract, **or** lean on `llm.py` vision OCR (Latin is trivial for it). See OCR. |
| `jlpt.py` | KanjiDic2 levels | CEFR has no good free per-word offline data → use **frequency bands** (open freq lists) or LLM-estimate, or drop. |

### Drop for Latin scripts
- `furigana.py` — no readings.
- `kanjivg.py` + the stroke-order validator in `web/stroke_match.js` / `practice.py`
  — no stroke order. Writing practice becomes copy-practice (see Writing).

---

## The one real refactor: a pluggable language backend

Introduce a small interface so `pipeline.py` is language-agnostic:

```
LanguageBackend:
    tokenize(text)      -> [ {s,l,r,p,p2}, ... ]      # r="" if no readings
    extract_words(text) -> {verbs, nouns, adjectives}
    reading_html(text)  -> str   # furigana ruby for JP; identity/plain for Latin
    gloss(word, cat)    -> str   # bilingual dictionary
    level(word)         -> str   # "N5"/"A1"/freq-band/"" 
config: { translate_model, ocr_engine, has_readings, has_strokes }
```

- JP backend = current code (fugashi + jamdict + manga-ocr + KanjiVG).
- Latin backend = spaCy + FreeDict + PaddleOCR/Tesseract, `has_readings=False`,
  `has_strokes=False`.

Also parametrize the two places that hardcode JP specifics:
- `exercises.py` — it is **structurally neutral** (consumes the generic token
  dict) but hardcodes JP POS strings (`動詞/名詞/形容詞/助詞`) and assumes
  `furigana`. Abstract: POS labels come from the backend; the furigana-cloze
  exercise and particle exercise become optional/parametrized. (German **case**
  marking is the natural analog of the JP particle exercise.)
- `render.py` / `reader.py` — treat `furigana` as optional; show plain text when
  `has_readings=False`. JLPT badge becomes the chosen level scheme or hidden.

Everything downstream of the token dict is unchanged.

---

## OCR (the main swap)

manga-ocr is JP-only. For Latin/comics (no comic-bubble-specific benchmark exists;
test on samples):
- **`claude -p` vision** (already in `llm.py`) — strongest; Latin text is trivial,
  and it does OCR + correction + translation in one pass. **Recommended primary.**
- **PaddleOCR** — best on complex layouts and slanted boxes (comic-friendly),
  own detection+recognition, multilingual. **Recommended free/offline path.**
- **EasyOCR** — 80+ langs, word-level, robust on varied fonts.
- **Tesseract** — 100+ langs but char-level, weak on stylized comic fonts; only
  for clean print.

---

## Cleaning (erase bubble text → write-on panel) — mostly portable

**Key insight: cleaning ≠ recognition.** Cleaning = **detect** text regions →
**mask** text pixels → **inpaint/fill**. The JP-specific piece (manga-ocr) is a
*recognizer*; erasing text doesn't need to read it. The detector is
appearance-based (comic-tuned, script-agnostic in principle).

PanelCleaner is **configurable**: it ships a Tesseract OCR backend
(`pcleaner/ocr/ocr_tesseract.py` + `supported_languages`) selectable in its
profile, so its (optional) box-filtering OCR can run eng/deu/spa — and cleaning
mostly needs detect+inpaint anyway.

Inpaint nuance: text in a **white bubble** → fill white (trivial); text **over
art** → real inpainting (PanelCleaner uses LaMa). For a write-on workbook even a
crude white box is fine (the learner writes there).

Three approaches, in order of effort:
1. **Reuse PanelCleaner clean** — set its profile OCR → Tesseract+lang (install
   `tesseract-ocr` + language packs) or disable box-OCR; detector+inpaint do the
   work. Verify recall on a Western page. **Recommended start.**
2. **Decouple** — take text boxes from the chosen OCR (PaddleOCR / claude-vision),
   white-fill bubble boxes + cv2/LaMa inpaint over-art. Independent of
   PanelCleaner's manga-tuned detector.
3. **Skip cleaning** — shadow-writing doesn't require an erased panel; show the
   original + a blank ruled writing area. Safety net.

---

## Writing practice for Latin scripts

No stroke order → no `stroke_match.js` validation. Shadow/copy writing instead:
show the model line, write it on ruled lines / boxes below (the existing
write-on panel + genkō-style cells already provide this). Optionally a faint
trace of the word for the first pass. This is the maintainer's stated intent
("focus a lot less on the correct strokes").

Morphology drills are **more** valuable here than in JP: spaCy lemma+morph gives
strong conjugation drills (es tenses/person, de verb forms) and German
article/case drills (the analog of the JP particle exercise).

---

## Data sources
- **Bilingual dictionaries:** FreeDict (https://freedict.org — ~140 offline
  bilingual dicts incl. de-en, es-en) or Wiktextract / kaikki.org
  (https://pypi.org/project/wiktextract/ ; ready-made dicts:
  https://github.com/Vuizur/Wiktionary-Dictionaries).
- **Translation:** Helsinki-NLP opus-mt model per pair.
- **NLP:** spaCy language models (`*_core_web_sm` / `*_core_news_sm`).
- **Levels:** open frequency lists per language (CEFR per-word is not freely
  available offline; LLM-estimate or use frequency bands).
- **OCR comparison refs:** PaddleOCR vs Tesseract vs EasyOCR (see chat research).

---

## First steps (for the worktree agent)
1. Branch a worktree off the latest (after `features/study-tools` merges).
2. Add the `LanguageBackend` interface; move current code into a `JaBackend`.
3. Implement `LatinBackend` (spaCy tokenize/POS/lemma → token dict; FreeDict or
   LLM glosses; `has_readings=False`, `has_strokes=False`).
4. Parametrize `exercises.py` POS labels + make furigana/particle exercises
   optional; add conjugation + (German) case drills.
5. OCR: wire `claude -p` vision first (fastest), add PaddleOCR as offline path.
6. Cleaning: try PanelCleaner with Tesseract profile; fall back to box-fill.
7. Generate an en→de or es→en sample; iterate on exercise quality.

## Open questions
- Source material: where do en/de/es comic pages come from as input?
- Per-pair gloss quality (FreeDict coverage vs Wiktextract vs LLM).
- Level scheme: frequency bands vs LLM CEFR estimate vs none.
