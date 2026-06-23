"""OCR via EasyOCR (text boxes); cleaning via the pcleaner CLI (erase bubbles).

EasyOCR reads the English text and returns reading-ordered boxes; pcleaner's
clean step (detection + inpainting, script-agnostic) still produces the blank
write-on page. pcleaner's own manga-ocr recogniser is unused here.
"""
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .panels import detect_panels, group_by_panel, order_boxes

VENV_BIN = Path(sys.executable).parent
PCLEANER = str(VENV_BIN / "pcleaner")

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_NUM = re.compile(r"(\d+)")
_PROG = re.compile(r"(\d+)/(\d+)")

# EasyOCR tuning. paragraph=True merges nearby lines into one box per speech
# bubble, which reads far better than per-line fragments (and matches how the old
# bubble-level OCR behaved). MIN_CONF drops junk detections; paragraph mode omits
# a confidence so the filter is a no-op there.
_OCR_LANGS = ["en"]
_OCR_PARAGRAPH = True
_OCR_MIN_CONF = 0.30


@lru_cache(maxsize=1)
def _reader():
    import easyocr
    import torch

    return easyocr.Reader(_OCR_LANGS, gpu=torch.cuda.is_available())


def _ocr_image(path: Path) -> list:
    """Run EasyOCR on one image -> [{x1,y1,x2,y2,text}, ...] (unordered)."""
    try:
        results = _reader().readtext(str(path), paragraph=_OCR_PARAGRAPH)
    except Exception:
        return []
    boxes = []
    for item in results:
        bbox, text = item[0], item[1]
        conf = item[2] if len(item) > 2 else 1.0
        text = (text or "").strip()
        if not text or conf < _OCR_MIN_CONF:
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        boxes.append({"x1": int(min(xs)), "y1": int(min(ys)),
                      "x2": int(max(xs)), "y2": int(max(ys)), "text": text})
    return boxes


def _natkey(name: str):
    """Natural sort key so 2.jpg < 10.jpg even without zero-padding."""
    return [int(t) if t.isdigit() else t.lower() for t in _NUM.split(name)]


def list_image_names(input_dir: Path):
    return sorted(
        (p.name for p in input_dir.iterdir() if p.suffix.lower() in IMG_EXT), key=_natkey
    )


def _sorted_paths(input_dir: Path):
    # Absolute paths: pcleaner silently writes nothing when given a relative
    # --output_dir, and resolving inputs too keeps everything unambiguous.
    return [str((input_dir / n).resolve()) for n in list_image_names(input_dir)]


def _run(args, cache_dir: Path, n_images=None, on_progress=None):
    # Isolate pcleaner's working cache per job so concurrent runs don't clobber
    # each other's temp files (XDG_CACHE_HOME controls where pcleaner writes).
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Force UTF-8 I/O: pcleaner prints non-ASCII to stdout, which crashes on
    # Windows' default cp1252 codec (UnicodeEncodeError). We also decode its output
    # as UTF-8 below to match.
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(cache_dir),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    if not (n_images and on_progress):
        proc = subprocess.run(
            [PCLEANER, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pcleaner {args[0]} failed:\n{proc.stderr[-2000:]}")
        return proc

    # Stream output and parse tqdm's per-image "X/Y" bar (Y == image count) for
    # fine-grained progress. pcleaner emits several sub-bars; only the one whose
    # total equals the number of input images tracks page-by-page progress.
    proc = subprocess.Popen(
        [PCLEANER, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
    )
    tail, buf, last = [], "", -1
    while True:
        ch = proc.stdout.read(1)
        if ch == "":
            break
        if ch in "\r\n":
            line, buf = buf.strip(), ""
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            m = None
            for m in _PROG.finditer(line):
                pass
            if m and int(m.group(2)) == n_images:
                done = int(m.group(1))
                if done != last:
                    last = done
                    on_progress(done, n_images)
        else:
            buf += ch
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"pcleaner {args[0]} failed:\n" + "\n".join(tail))
    return proc


def ocr_dir(input_dir: Path, cache_path: Path, on_progress=None, reuse=False, rtl=True) -> dict:
    """OCR every page with EasyOCR. Returns {filename: [box,...]} in reading order.
    Each box: {x1,y1,x2,y2,text}. on_progress(done, total) fires per image.
    reuse=True loads a cached JSON of boxes (same inputs assumed) instead of re-running.
    rtl=True orders panels/boxes right-to-left (manga); rtl=False is Western LTR."""
    cache_path = Path(cache_path)
    names = list_image_names(input_dir)
    if reuse and cache_path.exists():
        pages = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        pages = {}
        for i, name in enumerate(names, 1):
            pages[name] = _ocr_image(input_dir / name)
            if on_progress:
                on_progress(i, len(names))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    result = {}
    for name in names:
        boxes = pages.get(name, [])
        pw, ph = _page_size(input_dir / name)
        kept = [b for b in boxes if not _is_banner_box(b, pw, ph)]
        # Panel-aware order: split the page into panels (manga or Western reading
        # order) and sort boxes within each. Falls back to a flat sort when no panels.
        panels = detect_panels(input_dir / name, rtl=rtl)
        ordered = []
        for grp in group_by_panel(kept, panels):
            ordered += order_boxes(grp, rtl=rtl)
        result[name] = ordered
    return result


# Page-dominating display text (big title / SFX overlays) OCRs into junk "vocab",
# so drop it. Unlike a normal speech bubble — wide but a modest share of the page —
# a banner spans most of the width AND a large share of the height (big lettering).
# (Aspect-ratio filtering is wrong here: a normal horizontal line of dialogue is
# naturally wide, so it would be dropped.)
_BANNER_WIDTH = 0.60    # box width as a fraction of the page
_BANNER_HEIGHT = 0.18   # box height as a fraction of the page


def _page_size(path: Path):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)  # unknown -> filter no-ops, keep the box


def _is_banner_box(box, page_w, page_h) -> bool:
    w, h = box["x2"] - box["x1"], box["y2"] - box["y1"]
    if w <= 0 or h <= 0 or page_w <= 0 or page_h <= 0:
        return False
    return (w / page_w) >= _BANNER_WIDTH and (h / page_h) >= _BANNER_HEIGHT


def _rgb_inputs(imgs, scratch):
    """pcleaner writes the cleaned image in the input's file format, so an RGBA
    (alpha) source fails to save as JPEG ("cannot write mode RGBA as JPEG").
    Flatten any non-RGB input onto white into a scratch dir and swap those paths
    in, keeping the filename so the later *_clean mapping still matches."""
    conv_dir = scratch / "rgb_src"
    out = []
    for p in imgs:
        p = Path(p)
        try:
            with Image.open(p) as im:
                if im.mode in ("RGB", "L"):
                    out.append(p)
                    continue
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.split()[-1])
                conv_dir.mkdir(parents=True, exist_ok=True)
                dest = conv_dir / p.name
                flat.save(dest, quality=95)
                out.append(dest)
        except Exception:
            out.append(p)  # let pcleaner surface a real error rather than guessing
    return out


def clean_dir(input_dir: Path, out_dir: Path, on_progress=None, reuse=False) -> dict:
    """Run `pcleaner clean`. Returns {original_filename: cleaned_image_path}.
    reuse=True keeps existing cleaned images when all inputs already have one."""
    out_dir = Path(out_dir).resolve()  # pcleaner writes nothing for a relative dir
    out_dir.mkdir(parents=True, exist_ok=True)
    imgs = _rgb_inputs(_sorted_paths(input_dir), out_dir.parent)
    have = {p.name for p in out_dir.rglob("*_clean.*")}
    cached = bool(imgs) and all(
        any(n.startswith(Path(i).stem + "_clean") for n in have) for i in imgs)
    if not (reuse and cached):
        for old in out_dir.rglob("*_clean.*"):  # avoid pcleaner's overwrite prompt
            old.unlink()
        _run(["clean", *imgs, "--output_dir", str(out_dir), "--save-only-cleaned"],
             cache_dir=out_dir.parent / "pc_cache", n_images=len(imgs), on_progress=on_progress)
    cleaned = {p.name: p for p in out_dir.rglob("*_clean.*")}
    mapping = {}
    for img in imgs:
        stem = Path(img).stem
        match = cleaned.get(f"{stem}_clean.png") or cleaned.get(f"{stem}_clean.jpg")
        if not match:  # fallback: any cleaned file starting with stem
            match = next((v for k, v in cleaned.items() if k.startswith(stem + "_clean")), None)
        if match:
            mapping[Path(img).name] = match
    if imgs and not mapping:  # clean ran but produced nothing -> fail loudly, not blank panels
        raise RuntimeError(f"pcleaner clean wrote no cleaned images to {out_dir}")
    return mapping
