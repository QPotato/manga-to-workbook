"""Interactive HTML reader generated from a workbook.

A browser study view (vs the print PDF): each page's panel with its dialogue,
a global furigana toggle (hide readings to quiz yourself), per-line English
reveal, and optional per-line audio. Vocabulary summary with JMdict glosses and
JLPT badges. Self-contained HTML (inline images); audio, if requested, is
synthesised once with edge-tts (online, free) into a sibling folder.
"""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path

DEFAULT_VOICE = "ja-JP-NanamiNeural"
_MAX_EDGE = 900


def _data_uri(path: Path) -> str:
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


def synth_audio(texts, audio_dir, voice=DEFAULT_VOICE, on_progress=None) -> dict:
    """Synthesise each text to <audio_dir>/<hash>.mp3 (edge-tts, online, cached).
    Returns {text: filename or None}."""
    import edge_tts

    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    texts = [t for t in dict.fromkeys(t.strip() for t in texts) if t]
    mapping = {}

    async def one(text):
        name = hashlib.md5(text.encode()).hexdigest()[:16] + ".mp3"
        f = audio_dir / name
        if not f.exists():
            data = b""
            async for ch in edge_tts.Communicate(text, voice).stream():
                if ch["type"] == "audio":
                    data += ch["data"]
            f.write_bytes(data)
        return name

    async def run():
        for i, t in enumerate(texts, 1):
            try:
                mapping[t] = await one(t)
            except Exception:
                mapping[t] = None
            if on_progress:
                on_progress(i, len(texts))

    asyncio.run(run())
    return mapping


def build_reader_html(workbook, original_dir, out_html, audio=False,
                      voice=DEFAULT_VOICE, on_progress=None):
    original_dir, out_html = Path(original_dir), Path(out_html)
    pages_in = workbook["pages"]

    audio_rel, amap = "", {}
    if audio:
        texts = [d["plain"] for p in pages_in for d in p["dialog"]]
        texts += [e["word"] for cat in ("verbs", "nouns", "adjectives")
                  for e in workbook.get("summary_vocab", {}).get(cat, [])]
        audio_rel = out_html.stem + "_audio"
        amap = synth_audio(texts, out_html.parent / audio_rel, voice, on_progress)

    pages = []
    for p in pages_in:
        lines = [{"fur": d["furigana"], "en": d.get("en", ""),
                  "audio": amap.get(d["plain"].strip()) if audio else None}
                 for d in p["dialog"]]
        pages.append({"img": _data_uri(original_dir / p["filename"]), "lines": lines})

    sv = workbook.get("summary_vocab", {})
    vocab = {cat: [{"fur": e["furigana"], "en": e.get("en", ""), "jlpt": e.get("jlpt", ""),
                    "audio": amap.get(e["word"].strip()) if audio else None}
                   for e in sv.get(cat, [])] for cat in ("verbs", "nouns", "adjectives")}

    data = {"chapter": workbook.get("chapter", ""), "pages": pages, "vocab": vocab,
            "audioDir": audio_rel}
    html = _TMPL.replace("/*__DATA__*/", "DATA=" + json.dumps(data, ensure_ascii=False))
    out_html.write_text(html, encoding="utf-8")
    return out_html


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate the interactive HTML reader")
    ap.add_argument("workbook_json")
    ap.add_argument("original_dir")
    ap.add_argument("-o", "--out", default="reader.html")
    ap.add_argument("--audio", action="store_true", help="synthesise per-line audio (edge-tts, online)")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    a = ap.parse_args()
    wb = json.loads(Path(a.workbook_json).read_text(encoding="utf-8"))
    build_reader_html(wb, a.original_dir, a.out, audio=a.audio, voice=a.voice,
                      on_progress=lambda d, t: print(f"\raudio {d}/{t}", end="", flush=True))
    print(f"\nwrote {a.out}")


_TMPL = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Manga reader</title>
<style>
 *{box-sizing:border-box} body{font-family:system-ui,sans-serif;margin:0;color:#1a1a1a;background:#f6f6f4}
 #bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:8px 14px;display:flex;gap:18px;align-items:center;z-index:5}
 #bar label{font-size:14px;cursor:pointer} .wrap{max-width:900px;margin:0 auto;padding:14px}
 .page{margin:0 0 26px} .page img{max-width:100%;display:block;margin:0 auto;border:1px solid #ccc;background:#fff}
 .line{display:flex;align-items:baseline;gap:8px;padding:7px 4px;border-bottom:1px solid #eee}
 .ja{font-size:21px;flex:1} ruby rt{font-size:.5em;color:#666}
 body.hide-furi rt{visibility:hidden}
 .line button{font-size:12px;border:1px solid #ccc;background:#fafafa;border-radius:4px;padding:2px 7px;cursor:pointer;color:#444}
 .en{color:#557;font-size:15px;margin-left:6px} .en.hidden{display:none}
 h2{border-bottom:2px solid #333;padding-bottom:2px;font-size:16px;margin:22px 0 8px}
 .chips{display:flex;flex-wrap:wrap;gap:7px}
 .chip{position:relative;background:#eef;border:1px solid #ccd;border-radius:5px;padding:3px 8px;display:inline-flex;flex-direction:column;align-items:flex-start}
 .chip .w{font-size:15px} .chip .g{font-size:11px;color:#667} .chip .lvl{position:absolute;top:-7px;right:-5px;font-size:9px;background:#fde;color:#a44;border:1px solid #e9b;border-radius:3px;padding:0 2px}
 .chip button{margin-top:3px;font-size:11px;border:1px solid #ccd;background:#fff;border-radius:4px;cursor:pointer}
</style></head><body>
<div id="bar">
  <strong id="title"></strong>
  <label><input type="checkbox" id="furi" checked> furigana</label>
  <span style="color:#999;font-size:12.5px">Tap ▶ to listen, EN to reveal meaning.</span>
</div>
<div class="wrap"><div id="content"></div>
  <h2 id="vtitle">Vocabulary</h2>
  <div id="verbs"></div><div id="nouns"></div><div id="adjs"></div>
</div>
<script>
const /*__DATA__*/;
const audioEl = new Audio();
function play(name){ if(!name) return; audioEl.src = DATA.audioDir + "/" + name; audioEl.play(); }
const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function lineEl(l){
  const d = document.createElement("div"); d.className = "line";
  let h = `<span class="ja">${l.fur}</span>`;
  if(l.audio) h += `<button data-a="${l.audio}">▶</button>`;
  if(l.en) h += `<button class="ten">EN</button><span class="en hidden">${esc(l.en)}</span>`;
  d.innerHTML = h;
  const ab = d.querySelector("button[data-a]"); if(ab) ab.onclick = () => play(ab.dataset.a);
  const tb = d.querySelector(".ten"); if(tb) tb.onclick = () => d.querySelector(".en").classList.toggle("hidden");
  return d;
}
function chip(v){
  const c = document.createElement("span"); c.className = "chip";
  c.innerHTML = (v.jlpt?`<span class="lvl">${esc(v.jlpt)}</span>`:"") +
    `<span class="w">${v.fur}</span>` + (v.en?`<span class="g">${esc(v.en)}</span>`:"");
  if(v.audio){ const b=document.createElement("button"); b.textContent="▶"; b.onclick=()=>play(v.audio); c.appendChild(b); }
  return c;
}
function render(){
  document.getElementById("title").textContent = DATA.chapter || "Reader";
  const content = document.getElementById("content");
  DATA.pages.forEach(p=>{
    const pg = document.createElement("div"); pg.className = "page";
    if(p.img){ const im=document.createElement("img"); im.src=p.img; pg.appendChild(im); }
    p.lines.forEach(l=>pg.appendChild(lineEl(l)));
    content.appendChild(pg);
  });
  const cats = {verbs:"動詞 verbs", nouns:"名詞 nouns", adjs:"形容詞 adjectives"};
  const key = {verbs:"verbs", nouns:"nouns", adjs:"adjectives"};
  for(const id in cats){
    const box = document.getElementById(id); const items = DATA.vocab[key[id]] || [];
    if(!items.length){ continue; }
    const h = document.createElement("h2"); h.textContent = cats[id]; box.appendChild(h);
    const wrap = document.createElement("div"); wrap.className = "chips";
    items.forEach(v=>wrap.appendChild(chip(v))); box.appendChild(wrap);
  }
}
document.getElementById("furi").onchange = e => document.body.classList.toggle("hide-furi", !e.target.checked);
render();
</script></body></html>"""


if __name__ == "__main__":
    _main()
