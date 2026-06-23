"""Render workbook data -> PDF via WeasyPrint. Self-contained HTML/CSS, embeds images.

Each comic page produces two consecutive sheets: an images sheet (original panel +
blank practice copy) and a dialogue sheet (English + Spanish). The vocabulary
summary follows, then the exercises and answer-key appendix.
"""
import base64
import imghdr
from pathlib import Path

from weasyprint import HTML

CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", Arial, sans-serif;
       color: #111; margin: 0; }
.dialog .src, .v .word, .ex .item, .q .item, .answers .item { line-height: 1.6; }
h1 { font-size: 22pt; }
.summary h1 { margin-bottom: 12px; }
/* Vocabulary list: block entries flowed in CSS multi-columns. Avoids the flex/
   inline-flex chip layout that WeasyPrint renders as blank. */
.vocab-group { margin-bottom: 14px; }
.vocab-group h2 { border-bottom: 2px solid #333; padding-bottom: 2px; margin: 0 0 7px; font-size: 14pt; }
.vocab-group h2 .sub { font-size: 10pt; color: #888; font-weight: normal; }
.vocab-cols { column-count: 4; column-gap: 18px; }
.v { break-inside: avoid; margin: 0 0 7px; }
.v .word { font-size: 12pt; }
.v .es { display: block; font-size: 8.5pt; color: #667; }
.v .lvl { font-size: 7pt; border: 1px solid; border-radius: 3px; padding: 0 3px; margin-left: 5px;
          vertical-align: 1px; background: #eee; color: #555; border-color: #ccc; }
/* CEFR-style level colours: A1 blue (easiest) .. C2 red (hardest). */
.v .lvl.a1 { background: #e1ecff; color: #1d4ed8; border-color: #9db8f0; }
.v .lvl.a2 { background: #e3f6e3; color: #1f8a3b; border-color: #9ad6a3; }
.v .lvl.b1 { background: #fff6cc; color: #8a7000; border-color: #e6cf6b; }
.v .lvl.b2 { background: #ffe9d1; color: #c2620e; border-color: #f0bd86; }
.v .lvl.c1 { background: #ffe1e1; color: #c0271f; border-color: #f0a3a0; }
.v .lvl.c2 { background: #fbd5d5; color: #a01818; border-color: #e88; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.images { display: flex; gap: 8px; }
.images .col { flex: 1 1 50%; text-align: center; }
.images img { max-width: 100%; max-height: 188mm; object-fit: contain; border: 1px solid #ddd; }
.dialog { font-size: 12pt; }
.dialog .line { display: flex; gap: 12px; margin: 4px 0; padding-bottom: 4px;
                border-bottom: 1px solid #eee; break-inside: avoid; }
.dialog .src { flex: 1 1 50%; }
.dialog .tgt { flex: 1 1 50%; color: #555; }
.ex h1 { margin-bottom: 12px; }
.ex .sec { break-inside: avoid; margin-bottom: 14px; }
.ex .sec h2 { font-size: 14pt; border-bottom: 2px solid #333; padding-bottom: 2px; margin: 0 0 2px; }
.ex .instr { color: #666; font-size: 9.5pt; margin-bottom: 6px; }
.ex ol, .ex .grid { list-style: none; padding: 0; margin: 0; }
.ex .grid { display: flex; flex-wrap: wrap; gap: 6px 18px; }
.ex .item { break-inside: avoid; padding: 3px 0 22px; min-width: 0; }
.ex .grid .item { flex: 1 1 30%; padding-bottom: 16px; }
.qn { color: #888; font-weight: bold; margin-right: 4px; }
.big { font-size: 13pt; }
.blank { display: inline-block; min-width: 90px; border-bottom: 1px solid #999; }
.bank { color: #557; font-size: 9.5pt; margin-left: 8px; }
.answers .sec h2 { font-size: 12pt; }
.answers .item { font-size: 10pt; padding: 2px 0; }
.q .item { padding: 4px 0 8px; }
.q .write { height: 56px; border-bottom: 1px solid #ccc; margin-top: 4px; }
/* Build-info colophon: provenance for debugging a generated workbook. */
.colophon h1 { font-size: 16pt; color: #555; }
.colophon .meta { font-family: "Consolas", "Courier New", monospace; font-size: 9pt; color: #555; }
.colophon .row { display: flex; gap: 12px; padding: 2px 0; border-bottom: 1px solid #f0f0f0; }
.colophon .row .k { flex: 0 0 130px; color: #999; }
.colophon .row .v { flex: 1 1 auto; word-break: break-all; }
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _data_uri(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    data = path.read_bytes()
    # Sniff the real format: some sources are PNGs (often with alpha) mislabeled
    # .jpg, and an image/jpeg data URI for PNG bytes won't decode.
    kind = imghdr.what(None, h=data)
    mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
            "gif": "image/gif"}.get(kind) or (
        "image/png" if path.suffix.lower() == ".png" else "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _wordlist(words):
    if not words:
        return '<div class="v" style="color:#aaa">—</div>'
    out = []
    for w in words:
        gloss = f'<span class="es">{_esc(w["es"])}</span>' if w.get("es") else ""
        lvl = (f'<span class="lvl {_esc(w["level"].lower())}">{_esc(w["level"])}</span>'
               if w.get("level") else "")
        out.append(f'<div class="v"><span class="word">{_esc(w["word"])}</span>{lvl}{gloss}</div>')
    return "".join(out)


def _vocab_group(es_title, en_sub, words):
    return (f'<div class="vocab-group"><h2>{es_title} <span class="sub">{en_sub}</span></h2>'
            f'<div class="vocab-cols">{_wordlist(words)}</div></div>')


def _summary_section(vocab):
    return (
        '<section class="summary page">'
        '<h1>Vocabulario <span style="font-size:14pt;color:#888">Vocabulary</span></h1>'
        f'{_vocab_group("Verbos", "Verbs", vocab["verbs"])}'
        f'{_vocab_group("Sustantivos", "Nouns", vocab["nouns"])}'
        f'{_vocab_group("Adjetivos", "Adjectives", vocab["adjectives"])}'
        '</section>')


def _grammar_section(items):
    rows = "".join(
        f'<li class="item"><span class="big">{_esc(g["point"])}</span> '
        f'<span style="color:#666">{_esc(g["explain"])}</span>'
        f'<div style="color:#444;margin-top:2px">{_esc(g["example"])}</div></li>'
        for g in items)
    return f'<section class="ex page"><h1>Gramática</h1><ol>{rows}</ol></section>'


def _images(orig, cleaned):
    right = (
        f'<img src="{cleaned}">' if cleaned
        else '<div style="color:#aaa">(no cleaned image)</div>'
    )
    return f"""
      <div class="images">
        <div class="col"><img src="{orig}"></div>
        <div class="col">{right}</div>
      </div>"""


def _dialog(dialog):
    lines = "".join(
        f'<div class="line"><div class="src">{_esc(d["text"])}</div>'
        f'<div class="tgt">{_esc(d.get("es", ""))}</div></div>'
        for d in dialog
    ) or '<div class="line" style="color:#aaa">—</div>'
    return f'<div class="dialog">{lines}</div>'


def _page_sections(page, original_dir: Path):
    images = _images(_data_uri(original_dir / page["filename"]),
                     _data_uri(page["cleaned_path"]) if page["cleaned_path"] else "")
    dialog = _dialog(page["dialog"])
    # Two consecutive sheets per page: images, then its dialogue/translation.
    return (f'<section class="page images-sheet">{images}</section>'
            f'<section class="page dialog-sheet">{dialog}</section>')


def _exercise_section(ex):
    blocks = []
    for s in ex["sections"]:
        instr = f'<div class="instr">{s.get("instructions", "")}</div>' if s.get("instructions") else ""
        items = "".join(f'<li class="item">{it}</li>' for it in s["items"])
        layout = "grid" if len(s["items"]) > 10 else "list"
        blocks.append(f'<div class="sec"><h2>{s["title"]}</h2>{instr}'
                      f'<ol class="{layout}">{items}</ol></div>')
    return f'<section class="ex page"><h1>Ejercicios</h1>{"".join(blocks)}</section>'


def _answers_section(ex):
    blocks = []
    for s in ex["answers"]:
        items = "".join(f'<li class="item">{it}</li>' for it in s["items"])
        blocks.append(f'<div class="sec"><h2>{s["title"]}</h2><ol class="grid">{items}</ol></div>')
    return f'<section class="ex answers page"><h1>Solucionario</h1>{"".join(blocks)}</section>'


def _questions_section(questions):
    # The "final section with questions about what happens", with writing space;
    # the answer key for these is appended after the exercise key.
    items = "".join(
        f'<li class="item"><span class="qn">{i}.</span> {_esc(q["q"])}<div class="write"></div></li>'
        for i, q in enumerate(questions, 1)
    )
    return ('<section class="ex q page"><h1>Comprensión</h1>'
            '<div class="instr">Responde en español.</div>'
            f'<ol class="list">{items}</ol></section>')


def _question_answers(questions):
    items = "".join(
        f'<li class="item"><span class="qn">{i}.</span> {_esc(q["q"])} &mdash; {_esc(q["a"])}</li>'
        for i, q in enumerate(questions, 1)
    )
    return ('<section class="ex answers page"><h1>Comprensión — respuestas</h1>'
            f'<ol>{items}</ol></section>')


def _meta_section(meta):
    """Build-info colophon: commit, RNG seed, settings, environment (debug aid)."""
    s = meta.get("settings", {})
    rows = [
        ("Generated", meta.get("generated", "")),
        ("Commit", meta.get("commit", "")),
        ("Seed", meta.get("seed", "")),
        ("Chapter", s.get("chapter", "")),
        ("Pages", s.get("pages", "")),
        ("LLM", str(s.get("model")) if s.get("with_llm") else "off"),
        ("Reuse cache", "yes" if s.get("reuse") else "no"),
        ("Python", meta.get("python", "")),
        ("Platform", meta.get("platform", "")),
    ]
    body = "".join(
        f'<div class="row"><span class="k">{_esc(str(k))}</span>'
        f'<span class="v">{_esc(str(v))}</span></div>'
        for k, v in rows if v not in ("", None)
    )
    return f'<section class="page colophon"><h1>Build info</h1><div class="meta">{body}</div></section>'


def _wrap(inner, meta=None):
    generator = (f"<meta name='generator' content='manga-to-workbook "
                 f"{_esc(meta.get('commit', ''))}'>" if meta else "")
    return (f"<html><head><meta charset='utf-8'>{generator}<style>{CSS}</style></head>"
            f"<body>{inner}</body></html>")


def render_pdf(workbook: dict, original_dir, out_pdf):
    original_dir = Path(original_dir)
    # Pages first (images sheet + dialogue sheet per page), then the vocabulary
    # summary, then the exercises and answer-key appendix.
    body = [_page_sections(p, original_dir) for p in workbook["pages"]]
    body.append(_summary_section(workbook["summary_vocab"]))
    if workbook.get("grammar"):
        body.append(_grammar_section(workbook["grammar"]))
    ex = workbook.get("exercises")
    questions = workbook.get("questions")
    # Worksheets first (exercises, then comprehension), answer keys last.
    if ex and ex.get("sections"):
        body.append(_exercise_section(ex))
    if questions:
        body.append(_questions_section(questions))
    if ex and ex.get("sections"):
        body.append(_answers_section(ex))
    if questions:
        body.append(_question_answers(questions))
    meta = workbook.get("meta")
    if meta:
        body.append(_meta_section(meta))
    HTML(string=_wrap("".join(body), meta)).write_pdf(str(out_pdf))
    return out_pdf
