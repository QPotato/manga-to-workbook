# Manga → Japanese Study Workbook

Turn a manga chapter (a folder of page images) into a printable Japanese study
workbook PDF: vocabulary summary, per-page verb/noun/adjective lists, original page
beside a text-cleaned "write here" copy, and the dialogue with furigana.

## How it works

1. **OCR + text boxes** — [`pcleaner ocr`](https://pypi.org/project/pcleaner/) detects
   speech bubbles, OCRs them (manga-ocr inside), and returns reading-ordered text.
2. **Clean** — `pcleaner clean` erases bubble text → blank practice page.
3. **Furigana + POS** — [`fugashi`](https://pypi.org/project/fugashi/) (MeCab/unidic)
   adds hiragana readings and extracts verbs (dictionary form), nouns, adjectives.
4. **Render** — [WeasyPrint](https://weasyprint.org/) builds the PDF.

All dependencies come from **PyPI** — no local source checkouts needed.

## Install

```bash
python3.11 -m venv .venv && source .venv/bin/activate
# CPU-only torch first (avoids the multi-GB CUDA download):
pip install torch==2.12.1 torchvision==0.27.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
Needs a Japanese font installed (e.g. `fonts-noto-cjk`).

## Use

CLI:
```bash
python -m manga_workbook.pipeline <image_dir> -o workbook.pdf
```

Web (drop images → download PDF):
```bash
python app.py   # http://127.0.0.1:5000
```

## Layout

```
manga_workbook/        # decoupled core pipeline (no web deps)
  pcleaner_runner.py  # pcleaner OCR + clean wrappers (per-job cache isolation)
  language.py         # fugashi: furigana HTML + POS extraction
  furigana.py         # okurigana-aware reading placement
  workbook.py          # assemble workbook data + chapter vocab
  render.py           # workbook -> PDF (WeasyPrint)
  pipeline.py         # orchestrate; CLI entrypoint
app.py                # Flask frontend: upload images -> PDF
```

The cloned `PanelCleaner/`, `manga-ocr/`, `furigana/` folders are **not used** (the
tools are pulled from PyPI) and can be deleted.
