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

## Exercises / Questions section
Generated from data the pipeline ALREADY computes (OCR text, fugashi POS+lemmas,
furigana readings, opus-mt glosses, page order). Exercises = alternate renderings of
`booklet.json` — deterministic, offline, zero new heavy deps. **Seed all shuffles with a
fixed seed** (e.g. `random.Random(chapter_name)`) so output is reproducible.

### No-LLM drills (all buildable now)
1. **Furigana cloze** — render a dialog line's kanji WITHOUT `<rt>`; learner writes the
   reading. Answer = the ruby already generated (stage 4).
2. **Vocab recall / matching** — from header verb/noun/adj lists: JA→EN, EN→JA, or two
   shuffled columns to match. Answer key = opus-mt gloss.
3. **Conjugation drills** — surface form → dictionary form (食べた → 食べる).
   Answer = fugashi `.feature.lemma` (already extracted in stage 5).
4. **Fill-in-the-blank dialogue** — blank one extracted noun/verb in an OCR line; give a
   word bank from that page's header. Answer = removed token.
5. **Particle blanks** — blank 助詞 tokens (は/を/に/で); fugashi tags them.
   Answer = original particle.
6. **Sequencing** — shuffle a page's dialog lines; learner re-orders. Answer = original index.

### LLM comprehension questions (optional, ISOLATED add-on)
Open questions ("why did X happen?", "how does the character feel?") need semantics beyond
tokenization. Keep OUT of the core offline pipeline — gate behind a flag/separate stage so
the base build stays fully offline.
- **Stage 9 (optional)** `--with-comprehension` — feed per-page/chapter EN translations
  (already produced by opus-mt) + dialog to an LLM, prompt for N comprehension Qs + answer key.
- Provider TBD (local model or API). Cache results into `booklet.json` so re-renders need no
  re-call. If the flag is off, this section is simply omitted.

### Data model additions (extend stage-8 `booklet.json`)
```
exercises: {
  perPage: [ { index, cloze[], fillBlank[], particles[], sequencing{} } ],
  chapter: { vocabRecall[], conjugation[], comprehension[]? }  // comprehension only if --with-comprehension
}
answerKey: { ... }   // mirrors exercises, rendered as final appendix
```

## Webapp (Flask)
- Routes: `/` chapter list, `/booklet/<chapter>` reader, static for images.
- Page render matches CLAUDE.md layout:
  - top header: verb / noun / adjective lists
  - left: original page + furigana overlay (ruby)
  - right: cleaned page (blank, writable)
  - bottom: dialog text + EN translation (opus-mt)
- summary page first, exercises + answer-key appendix last (see Exercises section).
- `@media print` CSS → export booklet PDF from browser.

## Build order (milestones)
1. **M0 Env** — venv py3.11, install deps, import-smoke all 3 tools on `001.jpg`.
2. **M1 OCR spike** — detect boxes + OCR one page, print JSON. Validate quality.
3. **M2 Clean** — PanelCleaner produces blank page. Validate.
4. **M3 Lang** — furigana + POS extraction on OCR output.
5. **M4 Pipeline** — wire 1→8, emit booklet.json for full chapter, cache.
6. **M5 Webapp** — Flask reader rendering booklet.json, layout + print CSS.
7. **M6 Polish** — summary vocab page, reading order tuning, PDF export.
8. **M7 Exercises** — generate the 6 no-LLM drills from booklet.json + answer-key appendix; render in webapp.
9. **M8 Comprehension (optional)** — `--with-comprehension` LLM stage 9, cached into booklet.json, isolated from core.
10. **Later** — per-panel split, hosting, upload UI.

## Translation note (opus-mt-ja-en)
- `pip install sacremoses` may be needed (Marian tokenizer dep). Verify on first run.
- Model ~75M, downloads from HF first run, CPU-fine. Reuse one pipeline instance.
- Quality is rough for manga slang/fragments — acceptable per project ("not completeness").

## Open questions
- Reading order from box coords reliable? May need right-to-left sort heuristic.
- PanelCleaner CLI vs Python API — pick whichever exposes boxes + mask cleanly.
- Verb lemmatization: unidic gives lemma directly — verify covers conjugations.

---

## Roadmap — planned features

All build on the existing `workbook.json` (furigana, JMdict glosses, tokens,
exercises, + optional `claude -p` corrections/translations/questions). Ordered
by build dependency, with the primary goal (kanji writing) called out.

### Status
- ✅ **Reader** (#0): `reader.py` — furigana toggle, EN reveal, vocab+JLPT, optional audio.
- ✅ **Kanji writing practice** (#1, prototype): `practice.py` + `web/stroke_match.js` —
  KanjiVG stroke-order check (lenient), read→write→advance, mouse now / pen later.
- ✅ **Anki export** (#2): `anki.py`.
- ✅ **JLPT tagging** (#3): `jlpt.py` (chips + Anki tags).
- ✅ **TTS audio** (#4): edge-tts in the reader (online).
- ✅ **LLM grammar notes** (#6): `llm.grammar()` -> PDF + reader "文法" section.
- ✅ **OCR/clean cache reuse** (#7, caching half): `--reuse` skips pcleaner.
- ⬜ #5 genko sheets — covered by the writing-practice cells.
- ⬜ #7 panel-aware reading order — needs panel detection (research-grade); the
  row-band heuristic handles standard pages. Deferred.

### 0. Interactive HTML reader (foundation — build first)
Flask already serves; add a browser view of `workbook.json` (not just the PDF).
- Furigana **toggle** (hide readings → self-test → reveal), hover-for-gloss,
  exercise answer-reveal, "quiz/test" mode (readings + EN hidden).
- `@media print` stylesheet so any view (incl. the writing sheets below) prints
  to paper. This view is the host for kanji practice, audio, and quiz mode.

### 1. Kanji writing practice ★ PRIMARY GOAL (on the HTML reader)
Pull target kanji from the chapter's vocab/dialogue (practice them in context,
not isolated). Per kanji, a **practice cell**:
- genkō-yōshi (原稿用紙) square + cross guide-lines,
- faint **trace template** + **animated stroke order** from **KanjiVG**
  (open-source SVG stroke data, ~11k kanji, CC-BY-SA; files named by unicode
  codepoint; bundle the chapter's subset),
- a `<canvas>` overlay for pointer/touch/stylus drawing (clear/undo).
- Row progression **trace → freehand-in-grid → recall** (template fades across cells).
- **Print mode**: `@media print` hides canvas/buttons, prints guide + blank
  squares as a paper worksheet. One source → on-screen (stylus) or paper (pen).
- Static **stroke-order display** (numbered) can also drop into the PDF.
- Later (optional, hard): handwriting recognition/grading — skip for v1.

### 2. Anki export (high ROI, low effort)
`.apkg` via `genanki` from data we already have: vocab cards
(word → reading + gloss + EN), sentence cards, and cloze cards from the furigana.
Optionally include audio (below) and the kanji stroke-order image.

### 3. JLPT tagging
Annotate vocab chips + kanji with N5–N1 level: kanjidic2 (grade/JLPT/frequency,
via jamdict) for kanji; a JLPT vocab wordlist for words. Enables level filtering
and difficulty display; feeds "new kanji this chapter" for the writing drills.

### 4. TTS audio (in the HTML reader)
Per-line + per-word playback. Offline via local **VOICEVOX** or `pyopenjtalk`;
attach to the reader (and optionally Anki cards). Needs the HTML reader (PDF
can't play audio).

### 5. Genkō-yōshi grids / handwriting sheets
Reusable squared-paper component for the writing cells (#1) and a general
sentence-copying practice section. Cheap CSS; prints cleanly.

### 6. Extend the LLM call (near-free — same request)
The `claude -p` correction call already runs per page; add output fields for
**correct context-dependent readings** (fixes the `1日→ついたち` counter residual
left by the heuristic) and **one-line grammar notes** per page (〜ている, passive/
causative, conditionals, …).

### 7. Pipeline: cache + panel-aware order
- Cache OCR + cleaned images per chapter so toggling the LLM or re-rendering
  doesn't redo the slow stages (saves time and `claude` cost).
- Panel-aware reading order (panel segmentation, or let the LLM order boxes) for
  busy multi-panel pages the row-band heuristic still mis-orders.

### Build order
HTML reader (0) → kanji writing practice (1) → Anki (2) → JLPT (3) →
TTS (4) / genkō grids (5) → LLM extension (6) → caching + panel order (7).

---

## Kanji reading quiz mode (new) — type-the-reading reader

A variation of the HTML reader (#0) for learning **kanji readings** by typing them
on a Latin keyboard, going through the manga **linearly, dialogue by dialogue**.

### Research basis (why typing, not multiple choice)
- **Testing/retrieval effect + generation effect** — producing the reading from
  memory (free typing) encodes far better than re-reading furigana or picking from
  options. This is the core lever.
- **Retrieval needs immediate feedback** — show what's right/wrong on submit.
- **Desirable difficulty** — furigana hidden by default; effort drives encoding.
- **Random kanji-table order** — prevents learning readings by table position
  instead of recognising the glyph (reshuffle each page load).

### MVP spec (LOCKED)
Layout, per page:
- **Full page image on top**, untouched (reuse `_data_uri`).
- **Side panel: table of unique kanji on the page, in random order** (reshuffled
  each load), each clickable → reveals all its on/kun readings.
- **Main column: dialogues one at a time**, in Japanese, **no furigana**.

Per-dialogue flow:
1. Show the JP line (the `plain` text, kanji visible, no readings).
2. **Input box** — user types on Latin keyboard; **live romaji→kana conversion**
   as they type (IME-like preview).
3. **Submit button**, dual behaviour:
   - **Correct** (typed kana == expected reading) → advance to next dialogue.
   - **Wrong** → colour the expected-reading display **red from the first
     mismatched kana onward**; user **retries forever** (no answer reveal).
4. After the last dialogue on a page → **advance to next page**.

Judging: compare **converted kana vs expected kana**, never the raw romaji string,
so any romaji mapping to the right kana passes (`shi`/`si`, `fu`/`hu`, おう etc.).

### Data sources (no new heavy deps — all already in the pipeline)
- **Expected per-line reading (full hiragana):** derive from the existing furigana
  data. `language.furigana_html`/`split_furigana` already map kana onto the kanji
  core via fugashi; reconstruct the line's full hiragana by concatenating ruby
  readings + plain-kana chunks (or add a `reading` field next to `furigana` in the
  stage-4 workbook build). Same caveat as furigana: digit+kanji counters
  (`1日`) are unreliable — skip judging those segments rather than mark wrong.
- **Kanji table readings (on/kun):** **KanjiDic2 via jamdict** — the same source
  `jlpt.py` already uses for kanji grade/level. `jam.lookup(<kanji>).chars[0]`
  exposes `on_readings` / `kun_readings`. No new dependency.
- **Unique kanji per page:** `furigana.is_kanji` over each page's joined `plain`.

### Implementation sketch (in `reader.py`)
- Extend the per-page `DATA` payload built in `build_reader_html` with, per page:
  `quiz: { lines: [{ ja, reading }], kanji: [{ k, on[], kun[] }] }`
  (image already embedded as `p.img`).
- Add the romaji→kana converter client-side. Prefer a tiny existing JS mapping
  (wanakana-style table inlined) over a new build dep, since the reader is a
  single self-contained HTML file with no bundler. **Decision to confirm:** inline
  a minimal romaji table vs. vendoring wanakana.
- New self-contained template (or a mode toggle in `_TMPL`): page image + shuffled
  kanji side table + one-dialogue-at-a-time quiz panel; JS holds page/line cursor,
  does kana conversion, first-mismatch red highlight, advance-on-correct.
- Reading-comparison helper: normalise both sides to hiragana (`jaconv` already a
  dep, or kana-normalise in JS), compare char-by-char to find first mismatch index
  for the red highlight.

### Pronunciation check (extension)
Optional second modality on the same quiz: instead of (or in addition to) typing
the reading, the learner **says it aloud**, and we verify the spoken reading.
- Mic capture → **whisper.cpp** transcribes the speech **to kana**.
- Normalise to hiragana and run the **same kana-judging** as the typed answer
  (compare vs expected reading, char-by-char, first-mismatch highlight). The judge
  is modality-agnostic — one comparison helper serves both keyboard and voice.
- Reuses the local voice stack (see "Voice conversation mode"): **no new API**.
- UX: a mic button next to the input box; a correct spoken reading advances the
  dialogue just like a correct typed one. Forces both recall *and* pronunciation.
- Caveat: whisper may mis-transcribe short single-word readings (no context) and
  long vowels (おう/おお); be lenient on vowel length and offer a retry / fallback
  to typing rather than hard-failing.

### Open / deferred
- Whole-line input (one box) is the MVP. A later step-up is per-kanji-word blanks
  (cloze) if long lines feel tedious — not in v1.
- No SRS / per-kanji exposure tracking / scaffolding fade in v1 (research-supported
  but deliberately out of scope for the first version).
- Persisting progress (which page/line) across reloads — deferred; v1 can start
  from the top each session.

## Voice conversation mode (new) — speak with an N5 tutor

Spoken practice: talk into a mic, the LLM replies in slow, easy N5 Japanese,
optionally grounded in the chapter's vocabulary/dialogue so practice reinforces
what the workbook just taught.

### No new API needed
The whole loop is **STT → LLM → TTS** and reuses what the project already has:
- **STT — whisper.cpp** (local, free, offline). Handles Japanese incl. learner
  accent. No API key.
- **LLM — DeepSeek**, the provider already wired in `llm.py` (`_deepseek_chat`).
  Text-only is fine for a chat turn. **No second provider.**
- **TTS — VOICEVOX** (local HTTP server on `localhost`, free), already named for
  TTS audio in #4 above. Exposes an explicit **speed/intonation** control, so we
  get genuinely slow, crisp pronunciation — not prompt-faked "slow".

So beyond the existing DeepSeek key, this adds **zero new external/paid APIs** —
just two local tools (whisper.cpp binary + VOICEVOX engine).

### Sketch
- New `llm.py` helper for a chat turn: system prompt pins **N5 grammar/vocab,
  one or two short sentences, slow/clear, rephrase on request**; optionally seed
  the system prompt with the current chapter's vocab + dialogue lines so the tutor
  stays on-topic. Reuses `_run`/`_deepseek_chat` (no JSON parse — free-text reply).
- Mic capture + whisper.cpp transcription → user turn text.
- DeepSeek reply → VOICEVOX synth at reduced `speedScale` → play in the reader.
- Lives in the HTML reader (mic + audio need the browser); a small local backend
  bridges whisper.cpp + VOICEVOX (both already local processes).

### Open / deferred
- Pronunciation feedback / scoring (compare user's whisper transcript to a target)
  — later; v1 is just conversation.
- Voice-activity / turn-taking polish (push-to-talk is fine for v1).
