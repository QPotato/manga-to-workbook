"""Generate a self-contained kanji writing-practice page from a workbook.

The read -> write -> advance ("shadow the manga") experience: each dialogue line
is shown with its panel; the learner copies the whole line across a strip of
cells (one per character) on a graphics tablet (or mouse), and each character is
checked against its KanjiVG stroke order leniently (order + direction, shape
loose; soft gate — advance any time). One self-contained HTML file: inline page
images + per-character stroke data + the matcher + the UI, opened straight in a
browser. No server.
"""
import base64
import io
import json
from pathlib import Path

from . import kanjivg
from .furigana import is_kanji

_WEB = Path(__file__).parent / "web"
_MAX_EDGE = 900   # downscale inlined page images


def _is_target(ch: str) -> bool:
    # characters we ask the learner to write: kanji + kana (KanjiVG has both)
    return is_kanji(ch) or ("ぁ" <= ch <= "ヿ" and ch not in "・ー゛゜")


def _page_data_uri(path: Path) -> str:
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if max(im.size) > _MAX_EDGE:
                im.thumbnail((_MAX_EDGE, _MAX_EDGE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72)
    except Exception:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_practice_html(workbook, original_dir, out_html, cache_dir, on_progress=None):
    original_dir, out_html = Path(original_dir), Path(out_html)
    pages = workbook["pages"]

    # prefetch unique target chars (cached) with progress
    uniq = []
    for p in pages:
        for d in p["dialog"]:
            for ch in d["plain"]:
                if _is_target(ch) and ch not in uniq:
                    uniq.append(ch)
    strokes_by_char = {}
    for i, ch in enumerate(uniq, 1):
        strokes_by_char[ch] = kanjivg.strokes(ch, cache_dir)
        if on_progress:
            on_progress(i, len(uniq))

    page_imgs = [_page_data_uri(original_dir / p["filename"]) for p in pages]
    lines = []
    for pi, p in enumerate(pages):
        for d in p["dialog"]:
            chars = [{"c": ch, "s": strokes_by_char.get(ch, []) if _is_target(ch) else []}
                     for ch in d["plain"]]
            lines.append({"p": pi, "fur": d["furigana"], "en": d.get("en", ""), "chars": chars})

    data = {"chapter": workbook.get("chapter", ""), "pages": page_imgs, "lines": lines,
            "viewbox": kanjivg.VIEWBOX}
    matcher = (_WEB / "stroke_match.js").read_text(encoding="utf-8")
    html = (_TMPL
            .replace("/*__MATCHER__*/", matcher)
            .replace("/*__DATA__*/", "DATA=" + json.dumps(data, ensure_ascii=False)))
    out_html.write_text(html, encoding="utf-8")
    return out_html


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate the kanji writing-practice HTML")
    ap.add_argument("workbook_json", help="path to a workbook.json")
    ap.add_argument("original_dir", help="dir with the original page images")
    ap.add_argument("-o", "--out", default="practice.html")
    ap.add_argument("--cache", default="kanjivg_cache", help="KanjiVG SVG cache dir")
    a = ap.parse_args()
    wb = json.loads(Path(a.workbook_json).read_text(encoding="utf-8"))
    build_practice_html(wb, a.original_dir, a.out, a.cache,
                        on_progress=lambda d, t: print(f"\rfetching strokes {d}/{t}", end="", flush=True))
    print(f"\nwrote {a.out}")


_TMPL = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kanji writing practice</title>
<style>
 *{box-sizing:border-box} body{font-family:system-ui,sans-serif;margin:0;color:#1a1a1a;background:#f6f6f4}
 #bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:8px 14px;
      display:flex;gap:14px;align-items:center;flex-wrap:wrap;z-index:5}
 #bar button{background:#3355cc;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:15px;cursor:pointer}
 #bar button:disabled{background:#bbb}
 #prog{font-weight:bold} #score{color:#2a7}
 .wrap{max-width:1100px;margin:0 auto;padding:14px}
 #pageimg{max-width:100%;max-height:46vh;display:block;margin:0 auto;border:1px solid #ccc;background:#fff}
 #model{font-size:30px;text-align:center;margin:14px 0 2px} ruby rt{font-size:.5em;color:#666}
 #en{text-align:center;color:#777;margin-bottom:12px}
 #strip{display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
 .cell{position:relative;width:140px;height:140px;background:#fff;border:1px solid #ccc;border-radius:6px;
       background-image:linear-gradient(#eee,#eee),linear-gradient(#eee,#eee);
       background-size:1px 100%,100% 1px;background-position:50% 0,0 50%;background-repeat:no-repeat;touch-action:none}
 .cell.done{border-color:#2a7;box-shadow:0 0 0 2px #2a7 inset}
 .cell.nostroke{display:flex;align-items:center;justify-content:center;color:#bbb;font-size:64px;background-image:none}
 .cell svg.guide{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
 .gstroke{fill:none;stroke:#e0e0e0;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}
 .cell canvas{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair}
 .cellbtns{position:absolute;bottom:-2px;right:2px;display:flex;gap:4px}
 .cellbtns button{font-size:11px;padding:2px 6px;border:1px solid #ccc;background:#fafafa;border-radius:4px;cursor:pointer;color:#444}
 .help{max-width:1100px;margin:6px auto 0;color:#888;font-size:12.5px;text-align:center}
 .attn{color:#aaa;font-size:11px;text-align:center;margin:18px 0}
</style></head><body>
<div id="bar">
  <button id="prev">&lsaquo; Prev</button>
  <span id="prog"></span><span id="score"></span>
  <button id="next">Next &rsaquo;</button>
</div>
<div class="help">Read the line, then copy it left&rarr;right on the tablet. Gray = model. Green stroke = right order &amp; direction; red = off. Soft &mdash; advance any time. Per cell: ✎ clear, ? show stroke order.</div>
<div class="wrap">
  <img id="pageimg" alt="page">
  <div id="model"></div><div id="en"></div>
  <div id="strip"></div>
</div>
<div class="attn">Stroke data: KanjiVG (Ulrich Apel), CC BY-SA 3.0.</div>
<script>/*__MATCHER__*/</script>
<script>
const /*__DATA__*/;
const SM = window.StrokeMatch, VB = DATA.viewbox, SIZE = 140, NS = "http://www.w3.org/2000/svg";
let li = 0;

function samplePath(d, n){
  const svg = document.createElementNS(NS,"svg"), p = document.createElementNS(NS,"path");
  p.setAttribute("d", d); svg.appendChild(p); svg.style.position="absolute"; svg.style.opacity=0;
  document.body.appendChild(svg);
  const L = p.getTotalLength() || 1e-6, out = [];
  for(let i=0;i<n;i++){ const pt = p.getPointAtLength(L*i/(n-1)); out.push([pt.x/VB, pt.y/VB]); }
  document.body.removeChild(svg); return out;
}
const refCache = {};
function refStrokes(paths){ const k = paths.join("|"); return refCache[k] || (refCache[k] = paths.map(d=>samplePath(d,16))); }

function guideSVG(paths){
  const svg = document.createElementNS(NS,"svg"); svg.setAttribute("viewBox","0 0 "+VB+" "+VB); svg.setAttribute("class","guide");
  const ps = paths.map(d=>{ const p=document.createElementNS(NS,"path"); p.setAttribute("d",d); p.setAttribute("class","gstroke"); svg.appendChild(p); return p; });
  svg._paths = ps; return svg;
}

function makeCell(ch){
  const cell = document.createElement("div"); cell.className = "cell";
  if(!ch.s.length){ cell.className = "cell nostroke"; cell.textContent = ch.c; return cell; }
  const ref = refStrokes(ch.s);
  const guide = guideSVG(ch.s); cell.appendChild(guide);
  const canvas = document.createElement("canvas"); canvas.width = canvas.height = SIZE; cell.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let strokes = [], cur = null, res = null;
  const pos = e => { const r = canvas.getBoundingClientRect(); return [(e.clientX-r.left)/r.width, (e.clientY-r.top)/r.height]; };
  function draw(){
    ctx.clearRect(0,0,SIZE,SIZE);
    strokes.forEach((st,i)=>{ const ok = res && res.results[i] && res.results[i].pass; drawStroke(st, ok ? "#22aa77" : (res ? "#dd4444" : "#3355cc")); });
    if(cur) drawStroke(cur, "#3355cc");
  }
  function drawStroke(st, color){
    if(st.length<1) return; ctx.strokeStyle=color; ctx.lineWidth=5; ctx.lineCap="round"; ctx.lineJoin="round"; ctx.beginPath();
    ctx.moveTo(st[0][0]*SIZE, st[0][1]*SIZE); for(let i=1;i<st.length;i++) ctx.lineTo(st[i][0]*SIZE, st[i][1]*SIZE);
    if(st.length===1) ctx.lineTo(st[0][0]*SIZE+0.1, st[0][1]*SIZE); ctx.stroke();
  }
  function evaluate(){ res = SM.matchChar(strokes, ref); cell.classList.toggle("done", res.done); draw(); updateScore(); }
  canvas.addEventListener("pointerdown", e=>{ e.preventDefault(); canvas.setPointerCapture(e.pointerId); cur=[pos(e)]; res=null; cell.classList.remove("done"); draw(); });
  canvas.addEventListener("pointermove", e=>{ if(!cur) return; cur.push(pos(e)); draw(); });
  function end(){ if(!cur) return; if(cur.length>1) strokes.push(cur); cur=null; evaluate(); }
  canvas.addEventListener("pointerup", end); canvas.addEventListener("pointerleave", end);
  const btns = document.createElement("div"); btns.className="cellbtns";
  const clr = document.createElement("button"); clr.textContent="✎"; clr.title="clear";
  clr.onclick=()=>{ strokes=[]; cur=null; res=null; cell.classList.remove("done"); draw(); updateScore(); };
  const hint = document.createElement("button"); hint.textContent="?"; hint.title="show stroke order";
  hint.onclick=()=>animate(guide);
  btns.appendChild(clr); btns.appendChild(hint); cell.appendChild(btns);
  cell._done = () => res && res.done;
  return cell;
}

function animate(guide){
  guide._paths.forEach((p,i)=>{ const L=p.getTotalLength(); p.style.transition="none"; p.style.stroke="#3355cc";
    p.style.strokeDasharray=L; p.style.strokeDashoffset=L;
    setTimeout(()=>{ p.style.transition="stroke-dashoffset .5s linear"; p.style.strokeDashoffset=0; }, 150+i*550); });
  setTimeout(()=>guide._paths.forEach(p=>{ p.style.stroke=""; p.style.strokeDasharray=""; p.style.strokeDashoffset=""; }), 150+guide._paths.length*550+700);
}

let cells = [];
function updateScore(){
  const writable = cells.filter(c=>c._done), done = writable.filter(c=>c._done()).length;
  document.getElementById("score").textContent = writable.length ? `  ${done}/${writable.length} written` : "";
}
function render(){
  const line = DATA.lines[li];
  document.getElementById("pageimg").src = DATA.pages[line.p] || "";
  document.getElementById("model").innerHTML = line.fur;
  document.getElementById("en").textContent = line.en || "";
  document.getElementById("prog").textContent = `Line ${li+1} / ${DATA.lines.length}`;
  const strip = document.getElementById("strip"); strip.innerHTML=""; cells=[];
  line.chars.forEach(ch=>{ const c=makeCell(ch); cells.push(c); strip.appendChild(c); });
  document.getElementById("prev").disabled = li===0;
  document.getElementById("next").disabled = li>=DATA.lines.length-1;
  updateScore();
}
document.getElementById("prev").onclick=()=>{ if(li>0){ li--; render(); window.scrollTo(0,0);} };
document.getElementById("next").onclick=()=>{ if(li<DATA.lines.length-1){ li++; render(); window.scrollTo(0,0);} };
render();
</script></body></html>"""


if __name__ == "__main__":
    _main()
