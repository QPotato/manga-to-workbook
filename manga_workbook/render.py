"""Render workbook data -> PDF via WeasyPrint. Self-contained HTML/CSS, embeds images.

Each manga page produces two consecutive sheets: an images sheet (original panel +
blank practice copy) and a dialogue sheet (furigana + English). The vocabulary
summary follows, then the exercises and answer-key appendix.
"""
import base64
from pathlib import Path

from weasyprint import HTML

CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans CJK JP", "Noto Serif CJK JP", "Yu Gothic",
       "Meiryo", "MS Gothic", sans-serif; color: #111; }
ruby rt { font-size: 0.55em; }
h1 { font-size: 22pt; }
.summary h1 { margin-bottom: 10px; }
.summary h2 { border-bottom: 2px solid #333; padding-bottom: 2px; margin: 0 0 6px; font-size: 14pt; }
.summary .cols { display: flex; gap: 16px; align-items: flex-start; }
.summary .group { flex: 1 1 0; min-width: 0; }
.group.nouns { flex: 1.4 1 0; }
.wordlist { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: #eef; border: 1px solid #ccd; border-radius: 5px; position: relative;
        padding: 3px 7px; display: inline-flex; flex-direction: column; align-items: flex-start; }
.chip .w { font-size: 11pt; }
.chip .g { font-size: 8pt; color: #667; margin-top: 1px; }
.chip .lvl { position: absolute; top: -7px; right: -5px; font-size: 6.5pt; background: #fde;
             color: #a44; border: 1px solid #e9b; border-radius: 3px; padding: 0 2px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.header { border: 1px solid #999; padding: 6px 8px; margin-bottom: 6px; font-size: 10pt; }
.header .row { margin: 2px 0; }
.header .label { font-weight: bold; display: inline-block; min-width: 48px; }
.images { display: flex; gap: 8px; }
.images .col { flex: 1 1 50%; text-align: center; }
.images img { max-width: 100%; max-height: 150mm; object-fit: contain; border: 1px solid #ddd; }
.dialog { font-size: 12pt; }
.dialog .line { display: flex; gap: 12px; margin: 4px 0; padding-bottom: 4px;
                border-bottom: 1px solid #eee; break-inside: avoid; }
.dialog .ja { flex: 1 1 50%; }
.dialog .en { flex: 1 1 50%; color: #555; }
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
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _data_uri(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _wordlist(words):
    if not words:
        return '<span style="color:#aaa">—</span>'
    out = []
    for w in words:
        gloss = f'<span class="g">{_esc(w["en"])}</span>' if w.get("en") else ""
        lvl = f'<span class="lvl">{_esc(w["jlpt"])}</span>' if w.get("jlpt") else ""
        out.append(f'<span class="chip">{lvl}<span class="w">{w["furigana"]}</span>{gloss}</span>')
    return "".join(out)


def _summary_section(vocab):
    return f"""
    <section class="summary page">
      <h1>Vocabulary Summary</h1>
      <div class="cols">
        <div class="group verbs"><h2>動詞</h2><div class="wordlist">{_wordlist(vocab['verbs'])}</div></div>
        <div class="group nouns"><h2>名詞</h2><div class="wordlist">{_wordlist(vocab['nouns'])}</div></div>
        <div class="group adjs"><h2>形容詞</h2><div class="wordlist">{_wordlist(vocab['adjectives'])}</div></div>
      </div>
    </section>"""


def _grammar_section(items):
    rows = "".join(
        f'<li class="item"><span class="big">{_esc(g["point"])}</span> '
        f'<span style="color:#666">{_esc(g["explain"])}</span>'
        f'<div style="color:#444;margin-top:2px">{_esc(g["example"])}</div></li>'
        for g in items)
    return f'<section class="ex page"><h1>Grammar 文法</h1><ol>{rows}</ol></section>'


def _header(h):
    return f"""
      <div class="header">
        <div class="row"><span class="label">動詞</span>{" / ".join(h['verbs']) or "—"}</div>
        <div class="row"><span class="label">名詞</span>{" / ".join(h['nouns']) or "—"}</div>
        <div class="row"><span class="label">形容詞</span>{" / ".join(h['adjectives']) or "—"}</div>
      </div>"""


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
        f'<div class="line"><div class="ja">{d["furigana"]}</div>'
        f'<div class="en">{_esc(d.get("en", ""))}</div></div>'
        for d in dialog
    ) or '<div class="line" style="color:#aaa">—</div>'
    return f'<div class="dialog">{lines}</div>'


def _page_sections(page, original_dir: Path):
    header = _header(page["header"])
    images = _images(_data_uri(original_dir / page["filename"]),
                     _data_uri(page["cleaned_path"]) if page["cleaned_path"] else "")
    dialog = _dialog(page["dialog"])
    # Two consecutive sheets per page: images, then its dialogue/translation.
    return (f'<section class="page images-sheet">{header}{images}</section>'
            f'<section class="page dialog-sheet">{header}{dialog}</section>')


def _exercise_section(ex):
    blocks = []
    for s in ex["sections"]:
        instr = f'<div class="instr">{s.get("instructions", "")}</div>' if s.get("instructions") else ""
        items = "".join(f'<li class="item">{it}</li>' for it in s["items"])
        layout = "grid" if len(s["items"]) > 10 else "list"
        blocks.append(f'<div class="sec"><h2>{s["title"]}</h2>{instr}'
                      f'<ol class="{layout}">{items}</ol></div>')
    return f'<section class="ex page"><h1>Exercises 練習</h1>{"".join(blocks)}</section>'


def _answers_section(ex):
    blocks = []
    for s in ex["answers"]:
        items = "".join(f'<li class="item">{it}</li>' for it in s["items"])
        blocks.append(f'<div class="sec"><h2>{s["title"]}</h2><ol class="grid">{items}</ol></div>')
    return f'<section class="ex answers page"><h1>Answer Key 解答</h1>{"".join(blocks)}</section>'


def _questions_section(questions):
    # The "final section with questions about what happens" (CLAUDE.md), with
    # writing space; the answer key for these is appended after the exercise key.
    items = "".join(
        f'<li class="item"><span class="qn">{i}.</span> {_esc(q["q"])}<div class="write"></div></li>'
        for i, q in enumerate(questions, 1)
    )
    return ('<section class="ex q page"><h1>Comprehension 内容理解</h1>'
            '<div class="instr">Answer in English or Japanese.</div>'
            f'<ol class="list">{items}</ol></section>')


def _question_answers(questions):
    items = "".join(
        f'<li class="item"><span class="qn">{i}.</span> {_esc(q["q"])} &mdash; {_esc(q["a"])}</li>'
        for i, q in enumerate(questions, 1)
    )
    return ('<section class="ex answers page"><h1>Comprehension answers 解答</h1>'
            f'<ol>{items}</ol></section>')


def _wrap(inner):
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body>{inner}</body></html>")


def render_pdf(workbook: dict, original_dir, out_pdf):
    original_dir = Path(original_dir)
    # Manga first (images sheet + dialogue sheet per page), then the vocabulary
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
    HTML(string=_wrap("".join(body))).write_pdf(str(out_pdf))
    return out_pdf
