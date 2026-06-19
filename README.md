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

The pipeline runs on **CPU by default and uses a CUDA GPU automatically when one is
available** — pcleaner (OCR + cleaning) and the translation model both detect CUDA at
runtime. There is no flag to set: install the GPU build of PyTorch and it just uses it.

## Install (Linux / macOS, CPU)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
# CPU-only torch first (avoids the multi-GB CUDA download):
pip install torch==2.12.1 torchvision==0.27.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
Needs a Japanese font installed (e.g. `fonts-noto-cjk`).

## Install (Windows, with NVIDIA GPU)

The whole thing is much faster on a GPU. On a Windows desktop with an NVIDIA card:

1. **Install Python 3.11** (python.org) and create a venv:
   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\activate
   ```
2. **Install the CUDA build of PyTorch first.** Pick the index URL matching your CUDA
   version (check `nvidia-smi`; `cu124` works for recent drivers):
   ```powershell
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   ```
   Verify it sees the GPU:
   ```powershell
   python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   ```
3. **Install the rest:**
   ```powershell
   pip install -r requirements.txt
   ```
4. **WeasyPrint needs the GTK runtime on Windows** (for Pango/Cairo). Install the
   *GTK3 runtime for Windows* (e.g. the `tschoonj/GTK-for-Windows-Runtime-Environment-Installer`
   release), then restart the terminal. Without it, PDF rendering fails on import.
5. **Japanese font:** Windows ships *Yu Gothic* / *MS Gothic*, which the PDF already
   falls back to — nothing to install. (Installing Noto CJK gives nicer output.)

Then run it exactly as below; pcleaner and the translator will use the GPU on their own.
The first run downloads the model weights (a few hundred MB).

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
