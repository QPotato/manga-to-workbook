"""KanjiVG stroke data: per-character SVG stroke paths in stroke order.

KanjiVG (https://kanjivg.tagaini.net, CC-BY-SA 3.0) covers kanji AND kana, with
strokes stored in writing order — the reference for stroke-order practice. We
fetch the per-character SVG once and cache it; `strokes()` returns the ordered
list of SVG path `d` strings (the browser samples them into points for matching).
All glyphs share the 109x109 viewBox.
"""
import re
import urllib.request
from pathlib import Path

VIEWBOX = 109  # KanjiVG canvas is 0 0 109 109
_RAW = "https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{code}.svg"
_PATH = re.compile(r'<path[^>]*\bd="([^"]+)"')


def code(ch: str) -> str:
    return format(ord(ch), "05x")


def fetch_svg(ch: str, cache_dir) -> str | None:
    """Return the raw SVG for one character (cached on disk), or None if not found."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"{code(ch)}.svg"
    if f.exists():
        return f.read_text(encoding="utf-8")
    try:
        with urllib.request.urlopen(_RAW.format(code=code(ch)), timeout=30) as r:
            data = r.read().decode("utf-8")
    except Exception:
        return None
    f.write_text(data, encoding="utf-8")
    return data


def strokes(ch: str, cache_dir) -> list[str]:
    """Ordered list of SVG path `d` strings for `ch` (empty if KanjiVG lacks it)."""
    svg = fetch_svg(ch, cache_dir)
    return _PATH.findall(svg) if svg else []
