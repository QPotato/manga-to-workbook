"""Render workbook data -> PDF via WeasyPrint. Self-contained HTML/CSS, embeds images.

Per page we prefer a single sheet: header + images with the dialogue as a footer.
Only when that footer makes the page overflow do we split into two sheets
(images alone, with the images enlarged into the freed space) + a dialogue sheet.
"""
import base64
from pathlib import Path

from weasyprint import HTML

CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans CJK JP", "Noto Serif CJK JP", sans-serif; color: #111; }
ruby rt { font-size: 0.55em; }
h1 { font-size: 22pt; }
.summary { page-break-after: always; }
.summary h2 { border-bottom: 2px solid #333; padding-bottom: 2px; margin: 14px 0 6px; }
.wordlist { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { background: #eef; border: 1px solid #ccd; border-radius: 5px;
        padding: 4px 9px; display: inline-flex; flex-direction: column; align-items: flex-start; }
.chip .w { font-size: 13pt; }
.chip .g { font-size: 8.5pt; color: #667; margin-top: 1px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.header { border: 1px solid #999; padding: 6px 8px; margin-bottom: 6px; font-size: 10pt; }
.header .row { margin: 2px 0; }
.header .label { font-weight: bold; display: inline-block; min-width: 70px; }
.images { display: flex; gap: 8px; }
.images .col { flex: 1 1 50%; text-align: center; }
.images img { max-width: 100%; object-fit: contain; border: 1px solid #ddd; }
/* Landscape content height ~190mm; reserve room for the header (~22mm). */
.page.split .images img { max-height: 150mm; }
.page.footer .images img { max-height: 96mm; }
.dialog { font-size: 12pt; }
.footer .dialog { border-top: 1px solid #999; margin-top: 6px; padding-top: 5px; }
.dialog .line { display: flex; gap: 12px; margin: 4px 0; padding-bottom: 4px;
                border-bottom: 1px solid #eee; break-inside: avoid; }
.dialog .ja { flex: 1 1 50%; }
.dialog .en { flex: 1 1 50%; color: #555; }
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
        out.append(f'<span class="chip"><span class="w">{w["furigana"]}</span>{gloss}</span>')
    return "".join(out)


def _summary_section(vocab):
    return f"""
    <section class="summary">
      <h1>Vocabulary Summary</h1>
      <h2>Verbs 動詞</h2><div class="wordlist">{_wordlist(vocab['verbs'])}</div>
      <h2>Nouns 名詞</h2><div class="wordlist">{_wordlist(vocab['nouns'])}</div>
      <h2>Adjectives 形容詞</h2><div class="wordlist">{_wordlist(vocab['adjectives'])}</div>
    </section>"""


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


def _footer_page(header, images, dialog):
    return f'<section class="page footer">{header}{images}{dialog}</section>'


def _fits_one_page(section_html: str) -> bool:
    doc = HTML(string=f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
                      f"<body>{section_html}</body></html>").render()
    return len(doc.pages) <= 1


def _page_sections(page, original_dir: Path):
    header = _header(page["header"])
    images = _images(_data_uri(original_dir / page["filename"]),
                     _data_uri(page["cleaned_path"]) if page["cleaned_path"] else "")
    dialog = _dialog(page["dialog"])

    # Try the compact single-sheet layout (images + dialogue footer) first.
    footer = _footer_page(header, images, dialog)
    if not page["dialog"] or _fits_one_page(footer):
        return footer
    # Overflows: drop the footer, let images fill the sheet, dialogue on its own.
    images_sheet = f'<section class="page split">{header}{images}</section>'
    dialog_sheet = f'<section class="page">{header}{dialog}</section>'
    return images_sheet + dialog_sheet


def render_pdf(workbook: dict, original_dir, out_pdf):
    original_dir = Path(original_dir)
    body = [_summary_section(workbook["summary_vocab"])]
    body += [_page_sections(p, original_dir) for p in workbook["pages"]]
    html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(body)}</body></html>"
    HTML(string=html).write_pdf(str(out_pdf))
    return out_pdf
