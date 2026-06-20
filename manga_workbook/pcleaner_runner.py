"""Wrappers around the pcleaner CLI: OCR (boxes+text) and clean (blank pages)."""
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

VENV_BIN = Path(sys.executable).parent
PCLEANER = str(VENV_BIN / "pcleaner")

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_NUM = re.compile(r"(\d+)")
_PROG = re.compile(r"(\d+)/(\d+)")


def _natkey(name: str):
    """Natural sort key so 2.jpg < 10.jpg even without zero-padding."""
    return [int(t) if t.isdigit() else t.lower() for t in _NUM.split(name)]


def list_image_names(input_dir: Path):
    return sorted(
        (p.name for p in input_dir.iterdir() if p.suffix.lower() in IMG_EXT), key=_natkey
    )


def _sorted_paths(input_dir: Path):
    return [str(input_dir / n) for n in list_image_names(input_dir)]


def _run(args, cache_dir: Path, n_images=None, on_progress=None):
    # Isolate pcleaner's working cache per job so concurrent runs don't clobber
    # each other's temp files (XDG_CACHE_HOME controls where pcleaner writes).
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "XDG_CACHE_HOME": str(cache_dir)}

    if not (n_images and on_progress):
        proc = subprocess.run([PCLEANER, *args], capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"pcleaner {args[0]} failed:\n{proc.stderr[-2000:]}")
        return proc

    # Stream output and parse tqdm's per-image "X/Y" bar (Y == image count) for
    # fine-grained progress. pcleaner emits several sub-bars; only the one whose
    # total equals the number of input images tracks page-by-page progress.
    proc = subprocess.Popen(
        [PCLEANER, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env, bufsize=1,
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


def ocr_dir(input_dir: Path, csv_path: Path, on_progress=None) -> dict:
    """Run `pcleaner ocr`. Returns {filename: [box,...]} in reading order.
    Each box: {x1,y1,x2,y2,text}. on_progress(done, total) fires per image."""
    imgs = _sorted_paths(input_dir)
    csv_path.unlink(missing_ok=True)  # pcleaner prompts (and EOFErrors) if it exists
    _run(["ocr", *imgs, "--csv", "--output-path", str(csv_path)],
         cache_dir=csv_path.parent / "pc_cache", n_images=len(imgs), on_progress=on_progress)
    pages: dict = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pages.setdefault(row["filename"], []).append(
                {
                    "x1": int(row["startx"]),
                    "y1": int(row["starty"]),
                    "x2": int(row["endx"]),
                    "y2": int(row["endy"]),
                    "text": row["text"],
                }
            )
    result = {}
    for fname, boxes in pages.items():
        pw, ph = _page_size(input_dir / fname)
        kept = [b for b in boxes if not _is_banner_box(b, pw, ph)]
        result[fname] = _reading_order(kept)
    return result


# Cover/spine/banner display text: extreme aspect ratio + large. manga-ocr is
# trained on speech bubbles and badly garbles these (e.g. コードギアス spine ->
# "コードやアス、髪型ルーション"), so they poison furigana/vocab/translation. Drop them.
_BANNER_ASPECT = 6.0     # long:short side ratio
_BANNER_LONGSIDE = 0.4   # long side as a fraction of the page


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
    aspect = max(w / h, h / w)
    longside = max(w / page_w, h / page_h)
    return aspect >= _BANNER_ASPECT and longside >= _BANNER_LONGSIDE


def _reading_order(boxes):
    """Sort text boxes into manga reading order: top-to-bottom tiers, each read
    right-to-left. Boxes whose vertical centers fall within ~one line height form
    one tier, and the tier centroid updates as boxes join so a tier with mildly
    varying bubble heights stays together instead of splitting into top-to-bottom
    singletons (which would break the right-to-left order). Complex multi-character
    pages still need panel detection for perfect order."""
    if not boxes:
        return boxes
    heights = sorted(b["y2"] - b["y1"] for b in boxes)
    band = max(20, heights[len(heights) // 2])  # ~one median box height
    rows = []
    for b in sorted(boxes, key=lambda b: (b["y1"] + b["y2"]) / 2):
        cy = (b["y1"] + b["y2"]) / 2
        for row in rows:
            if abs(cy - row["cy"]) <= band:
                row["items"].append(b)
                row["cy"] = sum((x["y1"] + x["y2"]) / 2 for x in row["items"]) / len(row["items"])
                break
        else:
            rows.append({"cy": cy, "items": [b]})
    rows.sort(key=lambda r: r["cy"])
    ordered = []
    for row in rows:
        row["items"].sort(key=lambda b: (-b["x2"], b["y1"]))  # right edge first, then top
        ordered += row["items"]
    return ordered


def clean_dir(input_dir: Path, out_dir: Path, on_progress=None) -> dict:
    """Run `pcleaner clean`. Returns {original_filename: cleaned_image_path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.rglob("*_clean.*"):  # avoid pcleaner's overwrite prompt
        old.unlink()
    imgs = _sorted_paths(input_dir)
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
    return mapping
