"""End-to-end orchestration: image dir -> workbook PDF."""
import json
from pathlib import Path

from .meta import build_meta
from .workbook import apply_corrections, build_workbook
from .pcleaner_runner import clean_dir, list_image_names, ocr_dir
from .render import render_pdf


def list_images(input_dir: Path):
    return list_image_names(input_dir)


def run(input_dir, work_dir, out_pdf, chapter=None, log=print, progress=None,
        with_llm=False, llm_model=None, reuse=False, rtl=True, qwen_ocr=False):
    """progress(frac 0..1, msg) is called at each stage boundary and per page.
    qwen_ocr inserts a (slow, GPU) Qwen2.5-VL pass that re-reads each page and
    fixes EasyOCR's text errors before analysis. with_llm adds the DeepSeek
    translation-refine + Spanish Q&A stage at the back."""
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

    # Stage-end fractions. The optional Qwen OCR pass takes a band [o_end, q_end]
    # between detection and cleaning; the LLM Q&A stage gets the back half.
    if with_llm:
        o_end, c_end, a_end, f_correct, f_quest = 0.18, 0.33, 0.40, 0.85, 0.90
    else:
        o_end, c_end, a_end = (0.15, 0.60, 0.94) if qwen_ocr else (0.42, 0.77, 0.94)
        f_correct = f_quest = 0.0
    q_end = o_end + (c_end - o_end) * 0.7 if qwen_ocr else o_end

    ordered = list_images(input_dir)
    n = len(ordered)

    emit(0.02, f"Reading English text from {n} pages (OCR)...")
    ocr_pages = ocr_dir(
        input_dir, work_dir / "ocr.json", reuse=reuse, rtl=rtl,
        on_progress=lambda d, t: emit(0.02 + (o_end - 0.02) * d / t, f"OCR: page {d}/{t}"),
    )

    if qwen_ocr:
        from . import qwen_ocr as _qocr

        emit(o_end, "Qwen: correcting OCR text (vision model)...")
        ocr_pages = _qocr.correct_pages(
            input_dir, ocr_pages,
            on_progress=lambda d, t: emit(o_end + (q_end - o_end) * d / t, f"Qwen OCR: page {d}/{t}"),
        )
        _qocr.unload()  # free VRAM before the translation model loads

    emit(q_end, "Erasing speech bubbles (cleaning panels)...")
    cleaned_map = clean_dir(
        input_dir, work_dir / "cleaned", reuse=reuse,
        on_progress=lambda d, t: emit(q_end + (c_end - q_end) * d / t, f"Cleaning: page {d}/{t}"),
    )

    emit(c_end, "Extracting words and translating to Spanish...")

    def on_page(i, total):
        emit(c_end + (a_end - c_end) * (i / total), f"Analyzing page {i}/{total}...")

    workbook = build_workbook(ordered, ocr_pages, cleaned_map, chapter=chapter, on_page=on_page)

    model = None
    if with_llm:
        from . import llm

        model = llm_model or llm.DEFAULT_MODEL
        emit(a_end, f"AI ({model}): correcting OCR and translations...")
        pages_arg = [
            (p["filename"], str(input_dir / p["filename"]),
             [{"id": i, "text": d["text"]} for i, d in enumerate(p["dialog"], 1)])
            for p in workbook["pages"]
        ]
        corrections = llm.correct_pages(
            pages_arg, model,
            on_progress=lambda d, t: emit(a_end + (f_correct - a_end) * d / t, f"AI: page {d}/{t}"),
        )
        apply_corrections(workbook, corrections)
        emit(f_correct, "AI: writing comprehension questions...")
        lines = [(d["text"], d.get("es", "")) for p in workbook["pages"] for d in p["dialog"]]
        # Degrade gracefully: a JSON failure on these chapter-level calls leaves the
        # section empty rather than discarding the whole (already-built) workbook.
        try:
            workbook["questions"] = llm.comprehension(chapter, lines, model)
        except RuntimeError as e:
            log(f"AI: comprehension questions skipped: {e}")
            workbook["questions"] = []
        try:
            workbook["grammar"] = llm.grammar(chapter, lines, model)
        except RuntimeError as e:
            log(f"AI: grammar notes skipped: {e}")
            workbook["grammar"] = []
        emit(f_quest, "AI stage done.")

    workbook["meta"] = build_meta({
        "chapter": chapter,
        "pages": n,
        "with_llm": with_llm,
        "model": model,
        "reuse": reuse,
    })

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
    ap.add_argument("--with-llm", action="store_true",
                    help="Refine translations and add Spanish comprehension questions + grammar")
    ap.add_argument("--model", default=None,
                    help="DeepSeek model for translation refine + Spanish Q&A: "
                         "deepseek-chat (default) | deepseek-reasoner")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse cached OCR/cleaned in the work dir (same inputs) instead of re-running")
    ap.add_argument("--ltr", action="store_true",
                    help="left-to-right reading order (Western comics); default is right-to-left (manga)")
    ap.add_argument("--qwen-ocr", action="store_true",
                    help="re-read pages with the local Qwen2.5-VL vision model to fix OCR errors "
                         "on stylized lettering (GPU; weights cached under HF_HOME, e.g. E:/hf_cache)")
    a = ap.parse_args()
    run(a.input_dir, a.work, a.out, a.chapter, with_llm=a.with_llm, llm_model=a.model,
        reuse=a.reuse, rtl=not a.ltr, qwen_ocr=a.qwen_ocr)
