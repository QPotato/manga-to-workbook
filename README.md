---
title: Comic To English Workbook
emoji: 📖
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Comic → English Study Workbook (for Spanish speakers)

A spin-off of *manga-to-workbook*, retargeted **English → Spanish**: turn an
English comic chapter (a folder of page images) into a printable study workbook
PDF for Spanish-speaking learners — a Spanish-glossed vocabulary summary,
per-page verb/noun/adjective lists, the original page beside a text-cleaned
"write here" copy, and the dialogue with a Spanish translation.

> This branch (`english-for-spanish`) is a dedicated fork. The Japanese version
> lives on `features/study-tools`; the alphabet-specific features (furigana,
> kanji readings, stroke order, JLPT) are dropped here.

## How it works

1. **OCR + text boxes** — [EasyOCR](https://pypi.org/project/easyocr/) reads the
   English text and returns boxes; they're grouped into panels and ordered in
   reading order. The default is **right-to-left** (officially-translated manga
   keeps the original Japanese layout); pass `--ltr` for left-to-right Western comics.
2. **Clean** — [`pcleaner clean`](https://pypi.org/project/pcleaner/) erases bubble
   text → blank practice page (detection + inpainting; script-agnostic).
3. **Analyse** — [spaCy](https://spacy.io/) (`en_core_web_sm`) tokenizes, lemmatizes
   and tags, extracting verbs/nouns/adjectives in dictionary form.
4. **Gloss + level** — an offline FreeDict **en→es** dictionary gives the Spanish
   gloss; [`wordfreq`](https://pypi.org/project/wordfreq/) maps corpus frequency to
   a CEFR-style band (A1…C2).
5. **Translate** — [`Helsinki-NLP/opus-mt-en-es`](https://huggingface.co/Helsinki-NLP/opus-mt-en-es)
   gives the Spanish translation of each line (offline, no key).
6. **Render** — [WeasyPrint](https://weasyprint.org/) builds the PDF.

The pipeline runs on **CPU by default and uses a CUDA GPU automatically when one is
available** — EasyOCR, pcleaner, and the translation model all detect CUDA at
runtime. No flag to set: install the GPU build of PyTorch and it just uses it.

## Install (Windows, with NVIDIA GPU)

1. **Python 3.10/3.11** and a venv:
   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\activate
   ```
2. **Install the CUDA build of PyTorch first** (check `nvidia-smi`; `cu124` works
   for recent drivers — a Pascal 1080 Ti needs `torch>=2.6.0+cu124`):
   ```powershell
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   python -c "import torch; print(torch.cuda.is_available())"
   ```
3. **Install the rest, then the spaCy model:**
   ```powershell
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```
4. **WeasyPrint needs the GTK3 runtime on Windows** (Pango/Cairo). Install the
   *GTK3 runtime for Windows*, then restart the terminal.

CPU-only: swap step 2 for `--index-url https://download.pytorch.org/whl/cpu`.

The first run downloads model weights (EasyOCR + opus-mt, a few hundred MB).

## Use

CLI:
```bash
python -m manga_workbook.pipeline <image_dir> -o workbook.pdf        # manga (RTL)
python -m manga_workbook.pipeline <image_dir> -o workbook.pdf --ltr  # Western comic (LTR)
```

Web (drop images → download PDF):
```bash
python app.py   # http://127.0.0.1:5000
```

Optional AI refinement (`--with-llm`): natural Spanish translations + Spanish
comprehension questions & grammar notes via the DeepSeek API (`DEEPSEEK_API_KEY`).

### Fixing OCR on stylized lettering (`--qwen-ocr`)

EasyOCR reads clean lettering well but garbles grungy comic fonts (a systematic
U→L: `you→yol`, `because→becalse`). The optional `--qwen-ocr` flag re-reads each
page with a local **Qwen2.5-VL-3B** vision model and corrects the text while
keeping EasyOCR's reading order — fixing those errors offline:

```bash
HF_HOME=E:/hf_cache python -m manga_workbook.pipeline <image_dir> -o workbook.pdf --qwen-ocr
```

Needs a CUDA GPU (~8 GB VRAM; runs in fp16, no 4-bit). The ~7 GB of weights
download to the HuggingFace cache — **set `HF_HOME`** (e.g. `E:/hf_cache`) to keep
them off the system drive. Colour pages (covers/splashes) are skipped. It adds
~10 s/page, so it's opt-in.

### Translation: opus-mt (default) · `--qwen-translate` · `--with-llm` (DeepSeek)

After the (corrected) English is read, the Spanish translation comes from one of:

| option | engine | quality | needs |
|---|---|---|---|
| *(default)* | opus-mt-en-es | rough; occasional bad misses | offline |
| `--qwen-translate` | local Qwen2.5-VL | decent, fully offline; echoes ALL-CAPS, literal | GPU |
| `--with-llm` | DeepSeek API | **best** — natural & idiomatic | `DEEPSEEK_API_KEY` |

Benchmarked on Chainsaw Man: DeepSeek (`El cadáver se venderá bien en el mercado
negro`) > Qwen (`EL CUERPO LLEVARÁ UN DINERO GRANDE...`) > opus-mt (which fumbles
idioms, e.g. *finder's fee → "semen de la flor"*). For the best result use
**`--qwen-ocr --with-llm`** (clean English + natural Spanish); `--qwen-translate`
("full Qwen") is the best **fully-offline** path.

### Interactive HTML reader

```bash
python -m manga_workbook.reader work/workbook.json <image_dir> -o reader.html [--audio]
```
Each panel with its dialogue, a "show translation" toggle (hide the Spanish to
quiz comprehension), per-line Spanish reveal, the Spanish-glossed vocabulary with
level badges, and optional per-line **English** audio (`--audio`, edge-tts; pick a
voice with `--voice`, default `en-US-AriaNeural`).

### Copy-writing practice

```bash
python -m manga_workbook.practice work/workbook.json <image_dir> -o practice.html
```
Read each line, then copy it on a ruled writing sheet (stylus on a tablet, or
printed). No stroke-order validation — Latin script has none — with an optional
faint "trace" of the model line.

### Anki deck

```bash
python -m manga_workbook.anki work/workbook.json -o deck.apkg
```
Vocabulary cards (English → Spanish) and sentence cards (English line → Spanish).

Every generated output carries a build-info footer/colophon (git commit, RNG seed,
run settings, environment) so any stray file traces back to the build that made it.

## Layout

```
manga_workbook/        # decoupled core pipeline (no web deps)
  pcleaner_runner.py  # EasyOCR (boxes+text) + pcleaner clean (erase bubbles)
  qwen_ocr.py         # optional Qwen2.5-VL vision OCR-correction pass (--qwen-ocr)
  panels.py           # panel detection + reading order (RTL manga / --ltr Western)
  language.py         # spaCy: tokenize / lemma / POS word extraction
  dictionary.py       # offline FreeDict en->es glosses (data/en-es.json)
  level.py            # wordfreq -> CEFR-style level band
  translate.py        # opus-mt-en-es line translation
  workbook.py         # assemble workbook data + chapter vocab
  exercises.py        # offline study drills (seeded by chapter name)
  llm.py              # optional DeepSeek / claude refinement (en->es)
  render.py           # workbook -> PDF (WeasyPrint)
  reader.py           # workbook -> interactive HTML reader (optional audio)
  practice.py         # workbook -> copy-writing HTML
  anki.py             # workbook -> Anki .apkg
  meta.py             # build provenance (PDF + HTML)
  pipeline.py         # orchestrate; CLI entrypoint
  data/en-es.json     # prebuilt FreeDict eng-spa glosses
app.py                # Flask frontend: upload images -> PDF
data/build_dict.py    # one-time builder for data/en-es.json
```

## Data & licensing

The bundled `manga_workbook/data/en-es.json` is built from the
[FreeDict](https://freedict.org/) + [WikDict](http://www.wikdict.com/) `eng-spa`
dictionary (CC-BY-SA 3.0; base data from Wiktionary via DBnary). Rebuild it with
`python data/build_dict.py <eng-spa.tei>`.
