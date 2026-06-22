"""End-to-end orchestration: image dir -> workbook PDF."""
import json
from pathlib import Path

from .workbook import apply_corrections, build_workbook
from .pcleaner_runner import clean_dir, list_image_names, ocr_dir
from .render import render_pdf


def list_images(input_dir: Path):
    return list_image_names(input_dir)


def run(input_dir, work_dir, out_pdf, chapter=None, log=print, progress=None,
        with_llm=False, llm_model=None, reuse=False):
    """progress(frac 0..1, msg) is called at each stage boundary and per page.
    When with_llm is set, the free stages are compressed to leave room for the
    (slower) Claude correction + question stage; otherwise the budget is
    OCR 40% / clean 35% / analyze 17% / render 8%."""
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

    # Stage-end fractions: the LLM stage gets the back half when enabled.
    if with_llm:
        f_ocr, f_clean, f_analyze, f_correct, f_quest = 0.18, 0.33, 0.40, 0.85, 0.90
    else:
        f_ocr = f_clean = f_analyze = f_correct = f_quest = 0.0  # set below

    ordered = list_images(input_dir)
    n = len(ordered)
    o_end, c_end, a_end = (f_ocr, f_clean, f_analyze) if with_llm else (0.42, 0.77, 0.94)

    emit(0.02, f"Reading text from {n} pages (OCR)...")
    ocr_pages = ocr_dir(
        input_dir, work_dir / "ocr.csv", reuse=reuse,
        on_progress=lambda d, t: emit(0.02 + (o_end - 0.02) * d / t, f"OCR: page {d}/{t}"),
    )

    emit(o_end, "Erasing speech bubbles (cleaning panels)...")
    cleaned_map = clean_dir(
        input_dir, work_dir / "cleaned", reuse=reuse,
        on_progress=lambda d, t: emit(o_end + (c_end - o_end) * d / t, f"Cleaning: page {d}/{t}"),
    )

    emit(c_end, "Adding furigana, extracting words, translating...")

    def on_page(i, total):
        emit(c_end + (a_end - c_end) * (i / total), f"Analyzing page {i}/{total}...")

    workbook = build_workbook(ordered, ocr_pages, cleaned_map, chapter=chapter, on_page=on_page)

    if with_llm:
        from . import llm

        model = llm_model or llm.DEFAULT_MODEL
        emit(a_end, f"AI ({model}): correcting OCR and translations...")
        pages_arg = [
            (p["filename"], str(input_dir / p["filename"]),
             [{"id": i, "text": d["plain"]} for i, d in enumerate(p["dialog"], 1)])
            for p in workbook["pages"]
        ]
        corrections = llm.correct_pages(
            pages_arg, model,
            on_progress=lambda d, t: emit(a_end + (f_correct - a_end) * d / t, f"AI: page {d}/{t}"),
        )
        apply_corrections(workbook, corrections)
        emit(f_correct, "AI: writing comprehension questions...")
        lines = [(d["plain"], d.get("en", "")) for p in workbook["pages"] for d in p["dialog"]]
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
                    help="Refine translations and add Japanese comprehension questions + grammar")
    ap.add_argument("--model", default=None,
                    help="LLM model: deepseek-chat | deepseek-reasoner (DeepSeek API, default) "
                         "| opus | sonnet | haiku (local claude CLI, also fixes OCR)")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse cached OCR/cleaned in the work dir (same inputs) instead of re-running")
    a = ap.parse_args()
    run(a.input_dir, a.work, a.out, a.chapter, with_llm=a.with_llm, llm_model=a.model, reuse=a.reuse)
