"""Local Qwen2.5-VL vision OCR correction (optional, GPU).

EasyOCR reads clean lettering well but garbles stylized comic fonts (a systematic
U->L: you->yol, out->olt, because->becalse). Qwen2.5-VL re-reads each page image
and, anchored to EasyOCR's draft boxes, returns the correct English per box — so
the recognition is fixed while EasyOCR's panel reading order is preserved. English
only: translation stays with translate.py / llm.py (each tool on its strength).

Weights (~7 GB) download to the HuggingFace cache; set HF_HOME (e.g. E:/hf_cache)
to keep them off the system drive. Runs Qwen2.5-VL-3B in fp16 on a CUDA GPU
(~8 GB VRAM — fits an 11 GB 1080 Ti; no 4-bit needed). Colour pages (covers,
splashes) are skipped: stylized colour art garbles regardless and isn't the focus.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
_MIN_PIXELS = 256 * 28 * 28
_MAX_PIXELS = 1280 * 28 * 28   # cap image tokens so a tall page fits in VRAM
_MAX_NEW_TOKENS = 1024
_JSON = re.compile(r"(\{.*\}|\[.*\])", re.S)

_PROMPT = (
    "You are correcting the OCR of an English comic page. Below are draft text boxes "
    "as `id: text` in reading order. Using the image, return the correct English text "
    "for EACH id exactly as printed (fix OCR errors such as l/I, U read as L, 0/O). If "
    "a draft line is OCR noise rather than real readable text, return an empty string "
    'for it. Output ONLY JSON, no markdown: {{"boxes":[{{"id":1,"text":"..."}}]}}\n\n'
    "Draft:\n{draft}"
)


@lru_cache(maxsize=1)
def _model():
    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL, dtype=torch.float16, attn_implementation="sdpa", device_map="cuda")
    proc = AutoProcessor.from_pretrained(
        MODEL, min_pixels=_MIN_PIXELS, max_pixels=_MAX_PIXELS, use_fast=True)
    return model, proc


def unload():
    """Free the model + VRAM (call after the correction stage so the translation
    model has room on smaller GPUs)."""
    import torch

    _model.cache_clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _is_color_page(path, sat_thresh=0.15, frac=0.10) -> bool:
    """True if a meaningful fraction of pixels are saturated (a colour page)."""
    import numpy as np
    from PIL import Image

    try:
        with Image.open(path) as im:
            im = im.convert("HSV")
            im.thumbnail((200, 200))
            s = np.asarray(im)[:, :, 1] / 255.0
        return float((s > sat_thresh).mean()) > frac
    except Exception:
        return False


def _correct_one(image_path, boxes) -> dict | None:
    """Return {1-based id: corrected_text} for one page, or None on failure."""
    import torch
    from qwen_vl_utils import process_vision_info

    model, proc = _model()
    draft = "\n".join(f"{i}: {b['text']}" for i, b in enumerate(boxes, 1))
    msgs = [{"role": "user", "content": [
        {"type": "image", "image": str(image_path)},
        {"type": "text", "text": _PROMPT.format(draft=draft)}]}]
    text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    imgs, vids = process_vision_info(msgs)
    inp = proc(text=[text], images=imgs, videos=vids, padding=True,
               return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(**inp, max_new_tokens=_MAX_NEW_TOKENS, do_sample=False)
    res = proc.batch_decode([o[len(i):] for i, o in zip(inp.input_ids, out)],
                            skip_special_tokens=True)[0]
    m = _JSON.search(res)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    arr = data.get("boxes", []) if isinstance(data, dict) else data
    fixes = {}
    for b in arr:
        try:
            fixes[int(b["id"])] = str(b.get("text", "")).strip()
        except (KeyError, ValueError, TypeError):
            continue
    return fixes


def correct_pages(input_dir, ocr_pages, on_progress=None, skip_color=True) -> dict:
    """Rewrite each page's box text with Qwen's reading. Mutates and returns
    ocr_pages ({filename: [box,...]}). Boxes Qwen blanks as noise are dropped; a
    per-page failure keeps that page's original EasyOCR text. If the model can't be
    loaded at all (no GPU / OOM), aborts cleanly and returns the input unchanged."""
    input_dir = Path(input_dir)
    names = list(ocr_pages.keys())
    total = len(names)
    try:
        _model()  # surface a load failure once, before the per-page loop
    except Exception as e:
        print(f"  Qwen OCR unavailable, keeping EasyOCR text: {e}")
        return ocr_pages
    for k, name in enumerate(names, 1):
        boxes = ocr_pages.get(name) or []
        if boxes and not (skip_color and _is_color_page(input_dir / name)):
            try:
                fixes = _correct_one(input_dir / name, boxes)
            except Exception as e:
                print(f"  Qwen OCR failed for {name}, keeping original: {e}")
                fixes = None
            if fixes:
                kept = []
                for i, b in enumerate(boxes, 1):
                    t = fixes.get(i, b["text"])
                    if t:  # drop boxes Qwen judged to be noise
                        kept.append({**b, "text": t})
                ocr_pages[name] = kept
        if on_progress:
            on_progress(k, total)
    return ocr_pages
