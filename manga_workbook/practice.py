"""Generate a self-contained copy-writing practice page from a workbook.

The read -> write -> advance ("shadow the comic") experience for Latin script:
each dialogue line is shown with its panel, and the learner copies the whole line
onto a ruled writing area (with a stylus on a tablet, or printed and written by
hand). No stroke-order validation — Latin script has none — so this is plain
copy/shadow writing, with an optional faint trace of the model line for the first
pass. One self-contained HTML file: inline page images + the UI, opened straight
in a browser. No server.
"""
import base64
import io
import json
from pathlib import Path

from .meta import footer_html

_MAX_EDGE = 900   # downscale inlined page images


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


def build_practice_html(workbook, original_dir, out_html, on_progress=None):
    original_dir, out_html = Path(original_dir), Path(out_html)
    pages = workbook["pages"]

    page_imgs = [_page_data_uri(original_dir / p["filename"]) for p in pages]
    lines = []
    for pi, p in enumerate(pages):
        for d in p["dialog"]:
            text = d["text"].strip()
            if any(c.isalpha() for c in text):  # skip lines with nothing to copy ("...")
                lines.append({"p": pi, "text": text, "es": d.get("es", "")})

    data = {"chapter": workbook.get("chapter", ""), "pages": page_imgs, "lines": lines}
    html = _TMPL.replace("/*__DATA__*/", "DATA=" + json.dumps(data, ensure_ascii=False))
    html = html.replace("</body>", footer_html(workbook.get("meta")) + "</body>")
    out_html.write_text(html, encoding="utf-8")
    return out_html


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate the copy-writing practice HTML")
    ap.add_argument("workbook_json", help="path to a workbook.json")
    ap.add_argument("original_dir", help="dir with the original page images")
    ap.add_argument("-o", "--out", default="practice.html")
    a = ap.parse_args()
    wb = json.loads(Path(a.workbook_json).read_text(encoding="utf-8"))
    build_practice_html(wb, a.original_dir, a.out)
    print(f"wrote {a.out}")


_TMPL = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Práctica de escritura</title>
<style>
 *{box-sizing:border-box} body{font-family:system-ui,sans-serif;margin:0;color:#1a1a1a;background:#f6f6f4}
 #bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:8px 14px;
      display:flex;gap:14px;align-items:center;flex-wrap:wrap;z-index:5}
 #bar button{background:#3355cc;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:15px;cursor:pointer}
 #bar button:disabled{background:#bbb} #prog{font-weight:bold} #bar label{font-size:14px;cursor:pointer}
 .wrap{max-width:1000px;margin:0 auto;padding:14px}
 #pageimg{max-width:100%;max-height:42vh;display:block;margin:0 auto;border:1px solid #ccc;background:#fff}
 #model{font-size:30px;text-align:center;margin:14px 0 2px;font-weight:600}
 #es{text-align:center;color:#777;margin-bottom:12px}
 .sheet{position:relative;background:#fff;border:1px solid #ccc;border-radius:6px;margin:0 auto;touch-action:none}
 .sheet canvas{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair}
 .sheet .trace{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
               color:#e3e3e3;font-size:46px;pointer-events:none;user-select:none}
 .help{max-width:1000px;margin:6px auto 0;color:#888;font-size:12.5px;text-align:center}
 .tools{display:flex;gap:8px;justify-content:center;margin:8px 0}
 .tools button{font-size:13px;padding:4px 10px;border:1px solid #ccc;background:#fafafa;border-radius:5px;cursor:pointer;color:#444}
</style></head><body>
<div id="bar">
  <button id="prev">&lsaquo; Anterior</button>
  <span id="prog"></span>
  <button id="next">Siguiente &rsaquo;</button>
  <label><input type="checkbox" id="trace"> calco</label>
</div>
<div class="help">Lee la línea y cópiala en la hoja (con lápiz táctil o impresa). Activa «calco» para ver la línea modelo en gris detrás.</div>
<div class="wrap">
  <img id="pageimg" alt="página">
  <div id="model"></div><div id="es"></div>
  <div class="tools"><button id="clear">Borrar</button></div>
  <div class="sheet" id="sheet"></div>
</div>
<script>
const /*__DATA__*/;
let li = 0, showTrace = false;
const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function buildSheet(text){
  const sheet = document.getElementById("sheet");
  sheet.innerHTML = "";
  const W = Math.min(960, sheet.parentElement.clientWidth), ROWS = 3, RH = 64, H = ROWS*RH;
  sheet.style.width = W + "px"; sheet.style.height = H + "px";
  if(showTrace){
    for(let r=0;r<ROWS;r++){ const t=document.createElement("div"); t.className="trace";
      t.style.top=(r*RH)+"px"; t.style.height=RH+"px"; t.textContent=text; sheet.appendChild(t); }
  }
  const canvas = document.createElement("canvas"); canvas.width=W; canvas.height=H; sheet.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  // ruled baselines
  ctx.strokeStyle="#e6e6e6"; ctx.lineWidth=1;
  for(let r=1;r<=ROWS;r++){ ctx.beginPath(); ctx.moveTo(0,r*RH-8); ctx.lineTo(W,r*RH-8); ctx.stroke(); }
  let drawing=false, last=null;
  const pos=e=>{ const r=canvas.getBoundingClientRect(); return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height]; };
  canvas.addEventListener("pointerdown",e=>{ e.preventDefault(); canvas.setPointerCapture(e.pointerId); drawing=true; last=pos(e); });
  canvas.addEventListener("pointermove",e=>{ if(!drawing) return; const p=pos(e);
    ctx.strokeStyle="#1a1a1a"; ctx.lineWidth=3; ctx.lineCap="round"; ctx.beginPath(); ctx.moveTo(last[0],last[1]); ctx.lineTo(p[0],p[1]); ctx.stroke(); last=p; });
  const stop=()=>{ drawing=false; }; canvas.addEventListener("pointerup",stop); canvas.addEventListener("pointerleave",stop);
}
function render(){
  const line = DATA.lines[li];
  document.getElementById("pageimg").src = DATA.pages[line.p] || "";
  document.getElementById("model").textContent = line.text;
  document.getElementById("es").textContent = line.es || "";
  document.getElementById("prog").textContent = `Línea ${li+1} / ${DATA.lines.length}`;
  document.getElementById("prev").disabled = li===0;
  document.getElementById("next").disabled = li>=DATA.lines.length-1;
  buildSheet(line.text);
}
document.getElementById("prev").onclick=()=>{ if(li>0){ li--; render(); window.scrollTo(0,0);} };
document.getElementById("next").onclick=()=>{ if(li<DATA.lines.length-1){ li++; render(); window.scrollTo(0,0);} };
document.getElementById("clear").onclick=()=>render();
document.getElementById("trace").onchange=e=>{ showTrace=e.target.checked; render(); };
render();
</script></body></html>"""


if __name__ == "__main__":
    _main()
