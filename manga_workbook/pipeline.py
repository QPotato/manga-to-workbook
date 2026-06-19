"""End-to-end orchestration: image dir -> workbook PDF."""
import json
from pathlib import Path

from .workbook import build_workbook
from .pcleaner_runner import clean_dir, list_image_names, ocr_dir
from .render import render_pdf


def list_images(input_dir: Path):
    return list_image_names(input_dir)


def run(input_dir, work_dir, out_pdf, chapter=None, log=print, progress=None):
    """progress(frac: float 0..1, msg: str) is called at each stage boundary
    and per page during analysis. Stage budget: OCR 40%, clean 35%, analyze 17%, render 8%."""
    state = {"frac": 0.0}

    def emit(frac, msg):
        # pcleaner runs several passes over the images, so raw X/Y counts bounce
        # back to 0 each pass. Clamp the reported fraction to be monotonic.
        state["frac"] = max(state["frac"], frac)
        log(msg)
        if progress:
            progress(state["frac"], msg)

    input_dir = Path(input_dir)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    chapter = chapter or input_dir.name

    ordered = list_images(input_dir)
    n = len(ordered)
    emit(0.02, f"Reading text from {n} pages (OCR)...")
    ocr_pages = ocr_dir(
        input_dir, work_dir / "ocr.csv",
        on_progress=lambda d, t: emit(0.02 + 0.40 * d / t, f"OCR: page {d}/{t}"),
    )

    emit(0.42, "Erasing speech bubbles (cleaning panels)...")
    cleaned_map = clean_dir(
        input_dir, work_dir / "cleaned",
        on_progress=lambda d, t: emit(0.42 + 0.35 * d / t, f"Cleaning: page {d}/{t}"),
    )

    emit(0.77, "Adding furigana, extracting words, translating...")

    def on_page(i, total):
        emit(0.77 + 0.17 * (i / total), f"Analyzing page {i}/{total}...")

    workbook = build_workbook(ordered, ocr_pages, cleaned_map, chapter=chapter, on_page=on_page)
    (work_dir / "workbook.json").write_text(
        json.dumps(workbook, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    emit(0.94, "Rendering PDF...")
    render_pdf(workbook, input_dir, out_pdf)
    emit(1.0, "Done.")
    return out_pdf


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("-o", "--out", default="workbook.pdf")
    ap.add_argument("-w", "--work", default="work")
    ap.add_argument("-c", "--chapter")
    a = ap.parse_args()
    run(a.input_dir, a.work, a.out, a.chapter)
