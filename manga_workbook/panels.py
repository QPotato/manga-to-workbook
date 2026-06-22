"""Panel detection for manga reading order, via a recursive X-Y cut.

Manga is read panel-by-panel: tiers top-to-bottom, and right-to-left within a
tier. The free OCR gives text boxes but not panels, so a flat sort mis-orders
multi-panel pages. Here we split the page along its gutters (full-span runs that
match the page background) with a recursive X-Y cut, emit the panels already in
reading order, then assign each text box to its panel.

Heuristic and offline (numpy + PIL only). It is deliberately *conservative*:
- background-adaptive, so it works on light or dark pages (a gutter is any strip
  uniformly equal to the page's own background, white or black);
- it drops near-empty bands and bails out entirely (returns []) on pages it can't
  split cleanly or that fragment implausibly, so the caller falls back to the flat
  right-to-left/top-to-bottom sort. The result is thus never worse than that sort.

Borderless / bleed / dark full-page art has no usable gutters and falls back.
For pixel-perfect order on those, an ML manga detector (Magi/DASS) would be needed.
"""
import numpy as np
from PIL import Image

_BG_DELTA = 30       # a pixel is "content" if it differs from the page bg by > this
_EMPTY_FRAC = 0.012  # a row/col is "empty" (gutter) if <= this fraction is content
_MIN_GUTTER = 0.015  # a gutter must span >= this fraction of the page side
_MIN_PANEL = 0.08    # a panel must be >= this fraction of the page side
_MIN_CONTENT = 0.02  # a kept region must have >= this content fraction (drop blank bands)
_MAX_PANELS = 12     # more than this => implausible fragmentation, bail to flat sort
_MAX_DEPTH = 6


def _load_gray(image_path):
    try:
        with Image.open(image_path) as im:
            return np.asarray(im.convert("L"), dtype=np.int16)
    except Exception:
        return None


def _interior_empty_runs(profile, min_len):
    """(start, end) gutter runs: empty, >= min_len long, not touching an edge
    (edge runs are page margins, not gutters between panels)."""
    empty = profile <= _EMPTY_FRAC
    runs, n, i = [], len(empty), 0
    while i < n:
        if empty[i]:
            j = i
            while j < n and empty[j]:
                j += 1
            if i > 0 and j < n and (j - i) >= min_len:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _cut(content, x0, y0, x1, y1, depth, pw, ph):
    """Recursively split region [y0:y1, x0:x1] of the boolean content mask. Returns
    panel rects (x1,y1,x2,y2) in manga reading order. Horizontal gutters split into
    tiers (top->bottom); vertical gutters split into columns (right->left). Bands
    without enough content are dropped."""
    if depth >= _MAX_DEPTH or (y1 - y0) <= 0 or (x1 - x0) <= 0:
        return [(x0, y0, x1, y1)]
    sub = content[y0:y1, x0:x1]

    h_gutters = _interior_empty_runs(sub.mean(axis=1), max(4, int(_MIN_GUTTER * ph)))
    if h_gutters:
        bounds = [y0] + [y0 + (s + e) // 2 for s, e in h_gutters] + [y1]
        return _children(content, [(x0, a, x1, b) for a, b in zip(bounds, bounds[1:])],
                         depth, pw, ph, vertical=False)

    v_gutters = _interior_empty_runs(sub.mean(axis=0), max(4, int(_MIN_GUTTER * pw)))
    if v_gutters:
        bounds = [x0] + [x0 + (s + e) // 2 for s, e in v_gutters] + [x1]
        cols = [(a, y0, b, y1) for a, b in zip(bounds, bounds[1:])]
        return _children(content, cols, depth, pw, ph, vertical=True)

    return [(x0, y0, x1, y1)]


def _children(content, rects, depth, pw, ph, vertical):
    """Recurse into child rects, in manga order (columns right->left, tiers
    top->bottom), skipping ones too small or too empty to be real panels."""
    if vertical:
        rects = list(reversed(rects))  # right -> left
    out = []
    for (x0, y0, x1, y1) in rects:
        if (x1 - x0) < _MIN_PANEL * pw or (y1 - y0) < _MIN_PANEL * ph:
            continue
        if content[y0:y1, x0:x1].mean() < _MIN_CONTENT:
            continue  # blank band between panels
        out += _cut(content, x0, y0, x1, y1, depth + 1, pw, ph)
    return out


def detect_panels(image_path):
    """Return panel rects (x1,y1,x2,y2) in manga reading order, or [] when the page
    can't be split cleanly (single panel / dark bleed / implausible fragmentation)
    so the caller falls back to the flat sort."""
    g = _load_gray(image_path)
    if g is None:
        return []
    h, w = g.shape
    bg = int(np.median(g))                      # page background (white or dark)
    content = np.abs(g - bg) > _BG_DELTA        # anything not background = content
    panels = _cut(content, 0, 0, w, h, 0, w, h)
    if len(panels) <= 1 or len(panels) > _MAX_PANELS:
        return []
    return panels


# --- reading-order estimator ------------------------------------------------
# Ported from manga109/panel-order-estimator (MIT, (c) 2022 Hikaru Ikuta):
# the Kovanen et al. recursive binary space partition. Given a set of boxes it
# finds the highest-priority pivot line that cleanly separates them -- horizontal
# tiers (top->bottom) preferred, else vertical columns (right->left) -- recurses
# on each side, and concatenates, yielding manga reading order. A box that
# straddles a candidate pivot by more than _INTERCEPT_RATIO vetoes that pivot.
# Works on any boxes (panels or text), so it replaces our hand-rolled tier sort.
_INTERCEPT_RATIO = 0.25


def _pivot_side(zmin, zmax, pivot):
    """Side of `pivot` the span [zmin, zmax] sits on: 0 (>= pivot), 1 (<= pivot),
    or -1 (straddles it too much, so this pivot can't be used)."""
    if pivot <= zmin:
        return 1
    if zmax <= pivot:
        return 0
    r = (pivot - zmin) / (zmax - zmin)
    if min(r, 1 - r) > _INTERCEPT_RATIO:
        return -1
    return 0 if r > 0.5 else 1


def _split(boxes, pivot, horizontal):
    """Partition boxes by `pivot` into (side0, side1) in reading order (side0
    first): top before bottom for a horizontal pivot, right before left for a
    vertical one. Returns None if a box straddles the pivot or one side is empty."""
    side0, side1 = [], []
    for b in boxes:
        if horizontal:
            s = _pivot_side(b["y1"], b["y2"], pivot)
        else:  # negate x so "side 0" is the right (manga reads right-to-left)
            s = _pivot_side(-b["x2"], -b["x1"], -pivot)
        if s == -1:
            return None
        (side0 if s == 0 else side1).append(b)
    if not side0 or not side1:
        return None
    return side0, side1


def _highest_priority_division(boxes):
    """Best clean split of `boxes`: try horizontal pivots first (every box edge,
    top-down), then vertical (every box edge, right-to-left). None if undividable."""
    for p in sorted([b["y1"] for b in boxes] + [b["y2"] for b in boxes]):
        d = _split(boxes, p, horizontal=True)
        if d:
            return d
    for p in sorted([b["x1"] for b in boxes] + [b["x2"] for b in boxes], reverse=True):
        d = _split(boxes, p, horizontal=False)
        if d:
            return d
    return None


def order_boxes(boxes):
    """Return `boxes` (dicts with x1/y1/x2/y2) in manga reading order via the
    recursive binary space partition above. An undividable cluster (boxes that
    overlap on both axes) falls back to a top-to-bottom, right-to-left sort."""
    boxes = list(boxes)
    if len(boxes) <= 1:
        return boxes
    div = _highest_priority_division(boxes)
    if div is None:
        return sorted(boxes, key=lambda b: ((b["y1"] + b["y2"]) / 2, -(b["x1"] + b["x2"]) / 2))
    side0, side1 = div
    return order_boxes(side0) + order_boxes(side1)


def group_by_panel(boxes, panels):
    """Partition boxes into groups in panel reading order (by box centre). Boxes in
    no panel are returned as a final group so none are dropped. With no panels,
    returns a single group (caller then sorts it normally)."""
    if not panels:
        return [list(boxes)]
    groups = [[] for _ in panels]
    leftover = []
    for b in boxes:
        cx, cy = (b["x1"] + b["x2"]) / 2, (b["y1"] + b["y2"]) / 2
        for i, (x0, y0, x1, y1) in enumerate(panels):
            if x0 <= cx < x1 and y0 <= cy < y1:
                groups[i].append(b)
                break
        else:
            leftover.append(b)
    result = [g for g in groups if g]
    if leftover:
        result.append(leftover)
    return result
