"""Wrappers around the pcleaner CLI: OCR (boxes+text) and clean (blank pages)."""
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

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
    return pages


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
