---
title: Manga To Workbook
emoji: 📖
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Manga → Japanese Study Workbook

Point this at a folder of manga page images and it builds Japanese study material
from the chapter: a printable PDF workbook by default, and optionally an
interactive HTML reader, a kanji stroke-order practice page, and an Anki deck.

Everything works **fully offline** — OCR, furigana, dictionary glosses,
translation, and the exercises all run locally with no API key. An optional LLM
stage (DeepSeek or Claude) refines the translations and adds comprehension
questions on top.

## What you get

The PDF workbook contains, in order:

- **Per page**, two facing sheets:
  - the original panel beside a **text-cleaned "write here" copy** (bubbles erased),
    plus a per-page word list;
  - the **dialogue with furigana** and English, in panel reading order.
- **Vocabulary summary** — the chapter's most frequent verbs, nouns, and
  adjectives with furigana, English glosses (JMdict), and approximate JLPT levels.
- **Exercises** — furigana cloze, vocabulary recall, conjugation → dictionary
  form, fill-in-the-blank, particle drills, and panel sequencing — all generated
  deterministically from the chapter, with an **answer key** appendix.

Optional extra outputs (built from the same data, see [Other outputs](#other-outputs)):

- **Interactive HTML reader** — panels with a furigana toggle, per-line English
  reveal, and optional audio.
- **Kanji writing practice** — copy each line stroke-by-stroke on a tablet/mouse,
  checked against KanjiVG stroke order.
- **Anki deck** (`.apkg`) — vocabulary and sentence cards for spaced repetition.

## How it works

1. **OCR + bubble detection** — [`pcleaner`](https://pypi.org/project/pcleaner/)
   finds speech bubbles and OCRs them (manga-ocr inside).
2. **Panel-aware reading order** — a conservative recursive X-Y cut splits each
   page into panels (top-to-bottom, right-to-left) and orders the text boxes
   accordingly; pages it can't split cleanly fall back to a flat right-to-left sort.
3. **Clean** — `pcleaner` erases the bubble text to make the blank practice page.
4. **Language analysis** — [`fugashi`](https://pypi.org/project/fugashi/)
   (MeCab/unidic) adds furigana and extracts verbs (dictionary form), nouns, and
   adjectives. Glosses come from [JMdict](https://pypi.org/project/jamdict/) and
   JLPT levels from KanjiDic2 — both offline.
5. **Translation** — Helsinki-NLP `opus-mt-ja-en` translates the dialogue on CPU.
6. **(Optional) LLM stage** — refines translations and adds Japanese comprehension
   questions + grammar notes; see [AI enhancement](#optional-ai-enhancement).
7. **Render** — [WeasyPrint](https://weasyprint.org/) builds the PDF.

All dependencies come from **PyPI** — no local source checkouts. The pipeline runs
on **CPU by default and uses a CUDA GPU automatically when one is present** (both
pcleaner and the translator detect CUDA at runtime — there is no flag to set).

## Install

### Linux / macOS (CPU)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
# CPU-only torch first, so the multi-GB CUDA stack isn't pulled:
pip install torch==2.12.1 torchvision==0.27.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

Needs a Japanese font (e.g. `fonts-noto-cjk`).

### Windows (with NVIDIA GPU)

The whole pipeline is much faster on a GPU.

1. **Install Python 3.11** (python.org) and create a venv:
   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\activate
   ```
2. **Install the CUDA build of PyTorch first.** Pick the index URL matching your
   CUDA version (`nvidia-smi`; `cu124` works for recent drivers):
   ```powershell
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   ```
3. **Install the rest:**
   ```powershell
   pip install -r requirements.txt
   ```
4. **GTK runtime** — WeasyPrint needs Pango/Cairo on Windows. Install the *GTK3
   runtime for Windows* (e.g. the `tschoonj/GTK-for-Windows-Runtime-Environment-Installer`
   release) and restart the terminal, or PDF rendering fails on import.
5. **Japanese font** — Windows ships Yu Gothic / MS Gothic, which the PDF falls
   back to, so nothing to install (Noto CJK gives nicer output).

The first run downloads model weights (a few hundred MB).

## Usage

### Command line

```bash
python -m manga_workbook.pipeline <image_dir> -o workbook.pdf
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `-o, --out` | output PDF path (default `workbook.pdf`) |
| `-w, --work` | work dir for OCR/cleaned caches + `workbook.json` (default `work`) |
| `-c, --chapter` | chapter title (default: input folder name) |
| `--with-llm` | enable the optional LLM stage |
| `--model` | LLM model (see below) |
| `--reuse` | reuse cached OCR/cleaned output for the same inputs instead of re-running |

### Web app

Drop images in the browser, watch progress, download the PDF:

```bash
python app.py   # http://127.0.0.1:5000
```

The AI checkbox and model dropdown expose the same optional LLM stage.

## Optional AI enhancement

`--with-llm` (CLI) or the AI checkbox (web) runs an extra stage that produces
natural translations plus Japanese comprehension questions and grammar notes.
Results are cached into `workbook.json`, so re-rendering never re-calls the model.
Two providers:

- **DeepSeek** (`deepseek-chat` *(default)*, `deepseek-reasoner`) — text-only.
  Refines the rough translations and writes the Q&A + grammar notes. Needs an API
  key in `$DEEPSEEK_API_KEY` or a `DEEPSEEK_API_KEY` file in the project root. It
  can't see the page, so it doesn't change the OCR'd Japanese.
- **Claude** (`opus`, `sonnet`, `haiku`) — shells out to your local
  [Claude Code](https://claude.com/claude-code) (`claude`) CLI login (no API key
  or SDK). It has vision, so it can **also correct the Japanese OCR** from the page
  image.

Cost is billed to whichever account you choose.

## Other outputs

These build from the `workbook.json` the pipeline writes into the work dir:

```bash
# Anki deck (vocab + sentence cards)
python -m manga_workbook.anki work/workbook.json -o manga.apkg

# Interactive HTML reader (--audio synthesises per-line audio via edge-tts, online)
python -m manga_workbook.reader work/workbook.json <image_dir> -o reader.html [--audio]

# Kanji stroke-order writing practice (self-contained HTML)
python -m manga_workbook.practice work/workbook.json <image_dir> -o practice.html
```

## Docker / Hugging Face Spaces

The repo ships a `Dockerfile` (CPU, serves the Flask app on port 7860) used for
Hugging Face Spaces deployment:

```bash
docker build -t manga-workbook .
docker run -p 7860:7860 manga-workbook   # http://127.0.0.1:7860
```

## Project layout

```
manga_workbook/         # core pipeline (no web deps)
  pcleaner_runner.py   # pcleaner OCR + clean wrappers (per-job cache isolation)
  panels.py            # panel detection (recursive X-Y cut) for reading order
  language.py          # fugashi: furigana HTML + POS extraction
  furigana.py          # okurigana-aware reading placement
  dictionary.py        # offline JMdict (jamdict) glosses
  jlpt.py              # approximate JLPT level from KanjiDic2
  translate.py         # offline opus-mt-ja-en translation
  exercises.py         # deterministic offline study drills
  workbook.py          # assemble workbook data + chapter vocab
  llm.py               # optional DeepSeek / Claude enhancement
  render.py            # workbook -> PDF (WeasyPrint)
  reader.py            # workbook -> interactive HTML reader
  practice.py          # workbook -> kanji writing-practice HTML
  kanjivg.py           # KanjiVG stroke-order data (cached)
  anki.py              # workbook -> Anki .apkg
  pipeline.py          # orchestrate; CLI entrypoint
app.py                 # Flask frontend: upload images -> PDF
Dockerfile             # CPU image for the web app / HF Spaces
```
