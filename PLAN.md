# Build Plan — Manga → Japanese Study Booklet

## Decisions (locked)
- **Python webapp** run locally (Flask or FastAPI). Hosting later.
- Input = **full manga pages**, sorted by filename. Example: `dungeon-meshi-chapter-1/` (36 grayscale JPEGs).
- Booklet **unit = whole page** (page = "the panel"). No panel cropping ever. Still detect text boxes inside page for OCR crops + cleaning.
- **Translation: offline `Helsinki-NLP/opus-mt-ja-en`** (transformers pipeline, CPU, no key). Comprehension questions still deferred.
- Tools already cloned: PanelCleaner, manga-ocr, furigana.

## Architecture
Two parts, one repo:

```
[manga pages] → processing pipeline (Python) → booklet data (JSON + cleaned images)
                                              → web UI (Flask serves) → browser view / print PDF
```

- Pipeline = heavy, run once per chapter, cache output to disk.
- Webapp = serves cached booklet, renders pages, print CSS for PDF.

## Environment (DONE — M0 complete)
venv at `.venv` (Python 3.11). Install gotchas solved:
- py3.11 venv had no ensurepip (Debian) → bootstrapped pip via get-pip.py.
- Default torch pulls multi-GB CUDA stack → install **CPU-only**:
  `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`
- PanelCleaner local clone won't build → install from PyPI: `pip install pcleaner`.
- transformers 5.x breaks manga-ocr (`ViTImageProcessor` gone) → pin `transformers<5` (4.57.x).
- torch/torchvision must BOTH be `+cpu` builds or `torchvision::nms does not exist`.
- Always `--no-cache-dir` (disk was near full).
All verified working: pcleaner ocr/clean, fugashi POS+readings.

## Pipeline stages (SIMPLIFIED after M0 spike)
**Key finding:** `pcleaner ocr` already does detection + OCR + reading-order in one CSV
(cols: filename,startx,starty,endx,endy,text). `pcleaner clean` produces cleaned page + mask.
So detection/OCR/clean = ONE tool. furigana tool DROPPED — fugashi gives kana readings too.

1. **Load** — list dir, sort by filename.
2. **OCR+boxes** — `pcleaner ocr --csv` → per-box {coords, text} already in reading order.
3. **Clean** — `pcleaner clean` → `<dir>/cleaned/<name>_clean.jpg` blank write-on page (+ `_mask.png`).
4. **Furigana** — fugashi tokenize each OCR string → map kana (katakana→hiragana) onto kanji → ruby HTML.
5. **POS extract** — fugashi on full-page text → verbs(lemma=infinitive), nouns, adjectives; dedupe per page.
   (pos1: 動詞=verb, 名詞=noun, 形容詞=adj; `.feature.lemma` = dictionary form.)
6. **Translate** — `Helsinki-NLP/opus-mt-ja-en` (transformers `pipeline("translation")`, CPU).
   Translate whole-page joined dialog (not per-bubble) for context; also keep per-line EN.
   Lazy-load model once, reuse across pages. Manga register is rough → "best effort" only.
7. **Vocab summary** — frequency count across chapter → top words for summary page.
8. **Emit** `booklet.json`:
   ```
   { chapter, summaryVocab[], pages:[ { index, originalImg, cleanedImg,
       header:{verbs[],nouns[],adjectives[]},
       dialog:[{furiganaHtml, plain, en}] } ] }
   ```
   + write cleaned images to `output/<chapter>/cleaned/`.

## Webapp (Flask)
- Routes: `/` chapter list, `/booklet/<chapter>` reader, static for images.
- Page render matches CLAUDE.md layout:
  - top header: verb / noun / adjective lists
  - left: original page + furigana overlay (ruby)
  - right: cleaned page (blank, writable)
  - bottom: dialog text + EN translation (opus-mt)
- summary page first, questions section last (stub).
- `@media print` CSS → export booklet PDF from browser.

## Build order (milestones)
1. **M0 Env** — venv py3.11, install deps, import-smoke all 3 tools on `001.jpg`.
2. **M1 OCR spike** — detect boxes + OCR one page, print JSON. Validate quality.
3. **M2 Clean** — PanelCleaner produces blank page. Validate.
4. **M3 Lang** — furigana + POS extraction on OCR output.
5. **M4 Pipeline** — wire 1→8, emit booklet.json for full chapter, cache.
6. **M5 Webapp** — Flask reader rendering booklet.json, layout + print CSS.
7. **M6 Polish** — summary vocab page, reading order tuning, PDF export.
8. **Later** — comprehension questions, per-panel split, hosting, upload UI.

## Translation note (opus-mt-ja-en)
- `pip install sacremoses` may be needed (Marian tokenizer dep). Verify on first run.
- Model ~75M, downloads from HF first run, CPU-fine. Reuse one pipeline instance.
- Quality is rough for manga slang/fragments — acceptable per project ("not completeness").

## Open questions
- Reading order from box coords reliable? May need right-to-left sort heuristic.
- PanelCleaner CLI vs Python API — pick whichever exposes boxes + mask cleanly.
- Verb lemmatization: unidic gives lemma directly — verify covers conjugations.
