"""דף החיפוש: קובץ HTML אחד בתיקיית התוצאה. בלי שרת ובלי אינטרנט, נפתח בכל דפדפן.

מחפשים מילה (תגית, אלבום, שם של אדם, חודש או שנה) ורואים מיד את התמונות. לחיצה פותחת את הקובץ.
תמונות שסומנו כרגישות מוצגות מטושטשות בדף (הקובץ עצמו לא משתנה).
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter

from common import HEB_MONTHS, album_name

THUMBS = "_תמונות לחיפוש"

HTML = r"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>חיפוש בגלריה</title>
<style>
:root{--bg:#0f1420;--card:#182033;--line:#2a3550;--txt:#e9edf5;--dim:#9aa6bf;--acc:#f2b33d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,"Segoe UI",Arial,sans-serif}
header{position:sticky;top:0;background:rgba(15,20,32,.96);padding:16px 20px 10px;border-bottom:1px solid var(--line);z-index:2}
h1{margin:0 0 10px;font-size:20px}
#q{width:100%;font-size:18px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--txt)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--txt);border-radius:999px;padding:5px 12px;font-size:14px;cursor:pointer}
.chip.on{background:var(--acc);color:#1a1200;border-color:var(--acc)}
.chip small{color:var(--dim)}.chip.on small{color:#4a3800}
#count{color:var(--dim);font-size:14px;margin-top:8px}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;padding:16px 20px}
.it{position:relative;background:var(--card);border-radius:10px;overflow:hidden;cursor:pointer;aspect-ratio:1}
.it img{width:100%;height:100%;object-fit:cover;display:block}
.it .cap{position:absolute;inset:auto 0 0 0;padding:16px 8px 6px;font-size:12px;background:linear-gradient(transparent,rgba(0,0,0,.8))}
.it .vid{position:absolute;top:6px;left:6px;background:rgba(0,0,0,.65);border-radius:6px;padding:2px 6px;font-size:12px}
.more[hidden]{display:none}.more{display:block;margin:0 auto 30px;padding:10px 22px;font-size:16px;border-radius:10px;border:0;background:var(--acc);cursor:pointer}
</style></head><body>
<header><h1>חיפוש בגלריה</h1>
<input id="q" placeholder="מה מחפשים? קבלה, חוף, יום הולדת, שם של אדם, 2024..." autofocus>
<div class="chips" id="albums"></div><div class="chips" id="people"></div><div id="count"></div></header>
<div id="grid"></div><button class="more" id="more" hidden>עוד</button>
<script>
const D=__DATA__;
const grid=document.getElementById('grid'),q=document.getElementById('q'),cnt=document.getElementById('count'),more=document.getElementById('more');
let album=null,person=null,shown=0,list=[];
function norm(s){return (s||'').toLowerCase().replace(/[֑-ׇ]/g,'')}
D.items.forEach(x=>x.hay=norm([x.tag,x.album,(x.people||[]).join(' '),x.when,x.file,x.v?'סרטון וידאו':''].join(' ')));
function chips(el,vals,get,set){el.innerHTML='';vals.forEach(([k,n])=>{const b=document.createElement('button');
 b.className='chip'+(get()===k?' on':'');b.innerHTML='<bdi>'+k+'</bdi> <small>'+n+'</small>';
 b.onclick=()=>{set(get()===k?null:k);render()};el.appendChild(b)})}
function count(f){const c={};D.items.forEach(x=>f(x).forEach(k=>c[k]=(c[k]||0)+1));return Object.entries(c).sort((a,b)=>b[1]-a[1])}
const AL=count(x=>[x.album]),PE=count(x=>x.people||[]);
function render(){chips(document.getElementById('albums'),AL,()=>album,v=>album=v);
 chips(document.getElementById('people'),PE,()=>person,v=>person=v);
 const words=norm(q.value).split(/\s+/).filter(Boolean);
 list=D.items.filter(x=>(!album||x.album===album)&&(!person||(x.people||[]).includes(person))&&words.every(w=>x.hay.includes(w)));
 cnt.textContent=list.length+' מתוך '+D.items.length;grid.innerHTML='';shown=0;page()}
function page(){const end=Math.min(list.length,shown+300);for(;shown<end;shown++){const x=list[shown];
 const a=document.createElement('div');a.className='it';a.title=x.tag+' · '+x.when;
 a.innerHTML='<img loading="lazy" src="'+encodeURI(x.t)+'">'+(x.v?'<span class="vid">▶ '+x.v+'</span>':'')+'<div class="cap"><bdi>'+x.tag+'</bdi></div>';
 a.onclick=()=>window.open(encodeURI(x.f),'_blank');grid.appendChild(a)}
 more.hidden=shown>=list.length}
more.onclick=page;q.oninput=render;render();
</script></body></html>
"""


def build_search(run, dest, meta):
    tdir = dest / THUMBS
    tdir.mkdir(parents=True, exist_ok=True)
    items = []
    for m in meta:
        if not m.get("copy"):
            continue
        src = run / "thumbs" / f"{m['i']:05d}.jpg"
        t = tdir / f"{m['i']:05d}.jpg"
        if m.get("sensitive"):
            Image.open(src).filter(ImageFilter.GaussianBlur(10)).save(t, quality=80)
        else:
            shutil.copy(src, t)
        d = datetime.fromisoformat(m["date"])
        dur = m.get("duration") or 0
        items.append({
            "t": f"{THUMBS}/{t.name}", "f": m["copy"], "file": m.get("filename", ""),
            "tag": m.get("tag", ""), "album": album_name(m["album"]), "people": m.get("people") or [],
            "when": f"{d.day}.{d.month}.{d.year} {HEB_MONTHS[d.month - 1]} {d.year}",
            "v": (f"{int(dur // 60)}:{int(dur % 60):02d}" if m.get("kind") == "video" else ""),
            "_d": m["date"],
        })
    items.sort(key=lambda x: x["_d"], reverse=True)
    for x in items:
        del x["_d"]
    page = dest / "חיפוש בגלריה.html"
    page.write_text(HTML.replace("__DATA__", json.dumps({"items": items}, ensure_ascii=False)), encoding="utf-8")
    return page
