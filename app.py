"""Web frontend: drop manga images -> watch progress -> download workbook PDF."""
import json
import queue
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, request, send_file
from werkzeug.utils import secure_filename

from manga_workbook.pcleaner_runner import IMG_EXT
from manga_workbook.pipeline import run

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB upload cap

JOBS: dict = {}  # job_id -> {"q": Queue, "pdf": Path|None, "error": str|None}

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Manga -> Study Workbook</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#222}
 h1{font-size:22px} p{color:#555}
 .drop{border:2px dashed #99c;border-radius:10px;padding:40px;text-align:center;background:#f7f7ff;cursor:pointer}
 .drop.over{background:#eef;border-color:#55a}
 #list{margin:14px 0;font-size:14px;color:#444}
 button{background:#3355cc;color:#fff;border:0;border-radius:6px;padding:11px 20px;font-size:15px;cursor:pointer}
 button:disabled{background:#aaa;cursor:not-allowed}
 #bar{height:14px;background:#e6e6f2;border-radius:7px;overflow:hidden;margin:18px 0 6px;display:none}
 #fill{height:100%;width:0;background:#3355cc;transition:width .3s}
 #msg{font-size:14px;color:#3355cc;min-height:20px}
</style></head><body>
<h1>Manga &rarr; Japanese Study Workbook</h1>
<p>Drop the chapter's images (ordered by filename). You get a printable PDF workbook.</p>
<form id="f">
  <div class="drop" id="drop">Click or drop images here
    <input id="file" type="file" name="images" accept="image/*" multiple hidden></div>
  <div id="list"></div>
  <button id="go" type="submit" disabled>Build workbook PDF</button>
</form>
<div id="bar"><div id="fill"></div></div>
<div id="msg"></div>
<script>
const drop=document.getElementById('drop'),file=document.getElementById('file'),
 list=document.getElementById('list'),go=document.getElementById('go'),
 bar=document.getElementById('bar'),fill=document.getElementById('fill'),
 msg=document.getElementById('msg'),f=document.getElementById('f');
let files=[];
function setFiles(fl){files=[...fl].filter(x=>x.type.startsWith('image/'))
  .sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
  list.textContent=files.length?files.length+' images: '+files.map(x=>x.name).join(', '):'';
  go.disabled=!files.length;}
drop.onclick=()=>file.click();
file.onchange=()=>setFiles(file.files);
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};
drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');setFiles(e.dataTransfer.files)};
f.onsubmit=async e=>{e.preventDefault();go.disabled=true;bar.style.display='block';
  fill.style.width='0';msg.textContent='Uploading '+files.length+' images...';
  const fd=new FormData();files.forEach(x=>fd.append('images',x,x.name));
  let job;
  try{const r=await fetch('/build',{method:'POST',body:fd});
    if(!r.ok){msg.textContent='Error: '+(await r.text());go.disabled=false;return;}
    job=(await r.json()).job;}
  catch(err){msg.textContent='Error: '+err;go.disabled=false;return;}
  const es=new EventSource('/progress/'+job);
  es.onmessage=ev=>{const d=JSON.parse(ev.data);
    if(d.error){msg.textContent='Error: '+d.error;es.close();go.disabled=false;return;}
    if(d.frac!=null)fill.style.width=Math.round(d.frac*100)+'%';
    if(d.msg)msg.textContent=d.msg;
    if(d.done){es.close();msg.textContent='Done. Downloading PDF...';
      const a=document.createElement('a');a.href='/result/'+job;a.download='workbook.pdf';a.click();
      go.disabled=false;}};
  es.onerror=()=>{es.close();if(!msg.textContent.startsWith('Done'))msg.textContent='Connection lost.';
    go.disabled=false;};};
</script></body></html>"""


def _worker(job_id, in_dir, work_dir, out_pdf):
    job = JOBS[job_id]

    def progress(frac, m):
        job["q"].put({"frac": frac, "msg": m})

    try:
        run(in_dir, work_dir, out_pdf, progress=progress)
        job["pdf"] = out_pdf
        job["q"].put({"done": True, "frac": 1.0, "msg": "Done."})
    except Exception as e:
        job["error"] = str(e)
        job["q"].put({"error": str(e)})
    finally:
        job["q"].put(None)  # sentinel: stream end


@app.get("/")
def index():
    return PAGE


@app.post("/build")
def build():
    uploads = request.files.getlist("images")
    uploads = [u for u in uploads if u.filename and Path(u.filename).suffix.lower() in IMG_EXT]
    if not uploads:
        return Response("No images uploaded.", status=400)

    job_id = uuid.uuid4().hex
    base = Path(tempfile.gettempdir()) / f"workbook_{job_id}"
    in_dir = base / "input"
    in_dir.mkdir(parents=True)
    for u in uploads:
        u.save(in_dir / secure_filename(u.filename))

    JOBS[job_id] = {"q": queue.Queue(), "pdf": None, "error": None}
    threading.Thread(
        target=_worker, args=(job_id, in_dir, base / "work", base / "workbook.pdf"), daemon=True
    ).start()
    return {"job": job_id}


@app.get("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return Response("Unknown job.", status=404)

    def stream():
        while True:
            ev = job["q"].get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/result/<job_id>")
def result(job_id):
    job = JOBS.get(job_id)
    if not job or not job["pdf"]:
        return Response("Not ready.", status=404)
    return send_file(job["pdf"], mimetype="application/pdf",
                     as_attachment=True, download_name="workbook.pdf")


if __name__ == "__main__":
    import os

    # 0.0.0.0 so it works inside a container; PORT is set by the host (HF uses 7860).
    port = int(os.environ.get("PORT", "5000"))
    # threaded=True so SSE stream + the worker thread + downloads run concurrently
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
