"""שלב 2: מה יש בכל פריט, מה כפול, מה מטושטש, מה נוצר ב-AI, מי מופיע, ומה שייך לאיזה טיול.

- תוכן: מודל ראייה (Gemini, או OpenAI כשאין מפתח Gemini) רואה את העותקים המוקטנים (384px)
  במנות של 10 ומחזיר קטגוריה ותגית קצרה בעברית. הקטגוריות כוללות את האלבומים האישיים מ-albums.json.
- סרטונים: המודל רואה תמונה אחת מאמצע הסרטון.
- AI: סימן בקובץ עצמו (משלב 1) או זיהוי של המודל = אלבום "נוצר ב-AI".
- אנשים: אם יש תיקייה ~/.gallery-sorter/people/<שם>/ עם כמה תמונות, נבנה דף היכרות אחד
  שנשלח עם כל מנה, והמודל מחזיר מי מופיע בכל תמונה. בלי התיקייה, הפיצ'ר כבוי.
- כפולות: חתימה חזותית מקומית (dHash) + צולמו בהפרש של עד 10 דקות. מכל קבוצה נשארת החדה ביותר.
- מטושטשות: מדד חדות מקומי, ורק כשגם המודל מסכים (לא חל על סרטונים).
- טיולים: לפי ה-GPS. "בית" = האזור שבו צולמו הכי הרבה תמונות; ימים רצופים רחוק ממנו = טיול.

תוצאות המודל נשמרות בקאש, כך שהרצה חוזרת לא משלמת שוב.

  python scripts/classify.py --run ~/.gallery-sorter/runs/run1
"""
import argparse
import base64
import json
import math
import time
from collections import Counter
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from common import HEB_MONTHS, load_albums, people, provider

CATS = {k: v[1] for k, v in load_albums().items()}
PEOPLE = people()


def make_prompt():
    who = ""
    if PEOPLE:
        who = (f'- "people": list of names from the reference sheet ({", ".join(PEOPLE)}) that clearly appear in the image. '
               "Only use a name when the face really matches the reference sheet; otherwise an empty list.\n")
    return f"""You sort a person's phone camera roll. Some items are a single frame taken from a video.
For EACH image (numbered in order), return:
- "cat": exactly one key from this list (descriptions are in Hebrew):
{json.dumps(CATS, ensure_ascii=False, indent=1)}
- "tag": 2-4 Hebrew words naming what is in the image, specific (e.g. "חוף בים", "קבלה מסופר", "מתכון לעוגה").
- "blurry": true only if the image is clearly out of focus or motion-blurred.
- "accidental": true if it is an accidental shot (pocket, floor, black frame, finger).
- "sensitive": true if it shows private data (ID card, bank details, phone numbers in a private chat, passwords, nudity).
- "ai_generated": true if the whole image is clearly made by an AI image generator or is a digital illustration/render,
  not a real photo or a screenshot.
{who}Return ONLY a JSON array with one object per image, in the same order, each with keys n,cat,tag,blurry,accidental,sensitive,ai_generated{",people" if PEOPLE else ""}."""


PROMPT = make_prompt()


def people_sheet(run):
    """דף היכרות אחד: לכל אדם עד 4 תמונות בשורה, עם השם בצד. נשלח עם כל מנה."""
    f = run / "people_sheet.jpg"
    if f.exists() or not PEOPLE:
        return f if f.exists() else None
    cell, label = 192, 220
    sheet = Image.new("RGB", (label + cell * 4, cell * len(PEOPLE)), "white")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    for r, (name, pics) in enumerate(PEOPLE.items()):
        d.text((12, r * cell + cell // 2 - 15), f"#{r + 1}", fill="black", font=font)
        for c, p in enumerate(pics):
            try:
                im = ImageOps.fit(ImageOps.exif_transpose(Image.open(p)).convert("RGB"), (cell - 8, cell - 8))
                sheet.paste(im, (label + c * cell + 4, r * cell + 4))
            except Exception as e:
                print("people: skip", p, e)
    sheet.save(f, quality=85)
    return f


def sheet_legend():
    return "Reference sheet of known people, one row each: " + ", ".join(f"row #{k + 1} = {n}" for k, n in enumerate(PEOPLE))


class Fatal(Exception):
    """תקלה שאין טעם לנסות שוב (מפתח שגוי, נגמר הקרדיט)."""


def fatal_reason(msg):
    m = msg.lower()
    if "api key" in m or "api_key_invalid" in m or "permission_denied" in m or "incorrect api key" in m or " 401" in m:
        return "המפתח לא תקין. צרו מפתח חדש ושמרו אותו שוב."
    if "credits are depleted" in m or "insufficient_quota" in m or "billing" in m or " 402" in m:
        return "נגמר הקרדיט בחשבון של ספק המודל. טוענים קרדיט (או מחליפים מפתח) ומריצים שוב: מה שכבר סווג נשמר."
    return None


def ask_gemini(key, model, idxs, run):
    from google import genai
    from google.genai import types
    cl = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120000))
    parts = []
    sheet = people_sheet(run)
    if sheet:
        parts.append(types.Part.from_text(text=sheet_legend()))
        parts.append(types.Part.from_bytes(data=sheet.read_bytes(), mime_type="image/jpeg"))
    for k, i in enumerate(idxs, 1):
        parts.append(types.Part.from_text(text=f"Image {k}{VIDEO_NOTE.get(i, '')}:"))
        parts.append(types.Part.from_bytes(data=(run / "cls" / f"{i:05d}.jpg").read_bytes(), mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=PROMPT))
    r = cl.models.generate_content(model=model, contents=parts, config=types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.2))
    return json.loads(r.text)


def ask_openai(key, model, idxs, run):
    content = []
    sheet = people_sheet(run)
    if sheet:
        content += [{"type": "input_text", "text": sheet_legend()},
                    {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(sheet.read_bytes()).decode(),
                     "detail": "high"}]
    for k, i in enumerate(idxs, 1):
        b64 = base64.b64encode((run / "cls" / f"{i:05d}.jpg").read_bytes()).decode()
        content += [{"type": "input_text", "text": f"Image {k}{VIDEO_NOTE.get(i, '')}:"},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}", "detail": "low"}]
    content.append({"type": "input_text", "text": PROMPT + '\nWrap the array as {"items": [...]}.'})
    body = {"model": model, "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_object"}}, "reasoning": {"effort": "low"}}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode()[:300]}")
    text = "".join(c.get("text", "") for o in out.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text")
    j = json.loads(text)
    return j.get("items", j) if isinstance(j, dict) else j


VIDEO_NOTE = {}  # i -> " (frame from a video)"


def classify_batch(prov, model, run, idxs):
    name, key = prov
    for attempt in range(5):
        try:
            arr = (ask_gemini if name == "gemini" else ask_openai)(key, model, idxs, run)
            if len(arr) == len(idxs):
                return {i: a for i, a in zip(idxs, arr)}
            got = {idxs[a["n"] - 1]: a for a in arr if isinstance(a.get("n"), int) and 1 <= a["n"] <= len(idxs)}
            if got:
                return got
        except Exception as e:
            why = fatal_reason(str(e))
            if why:
                raise Fatal(why)
            print("retry", attempt, str(e)[:160], flush=True)
            time.sleep(5 * (attempt + 1))  # מגבלת קצב (במיוחד במסלול החינמי): מחכים ומנסים שוב
    return {}


def dhash(path, size=8):
    a = np.asarray(Image.open(path).convert("L").resize((size + 1, size), Image.LANCZOS), dtype=np.int16)
    return int("".join("1" if b else "0" for b in (a[:, 1:] > a[:, :-1]).flatten()), 2)


def sharpness(path):
    a = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    lap = a[1:-1, 1:-1] * -4 + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", help="ברירת מחדל: gemini-3-flash-preview, או gpt-5.4-mini כשהמפתח של OpenAI")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    run = Path(args.run).expanduser()
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    VIDEO_NOTE.update({m["i"]: " (frame from a video)" for m in meta if m.get("kind") == "video"})
    if PEOPLE:
        print("people:", ", ".join(PEOPLE), flush=True)

    # 1. סיווג תוכן
    cache_f = run / "gemini.json"
    cache = {int(k): v for k, v in json.loads(cache_f.read_text()).items()} if cache_f.exists() else {}
    cache = {k: v for k, v in cache.items() if v.get("tag")}
    prov = provider()
    model = args.model or ("gemini-3-flash-preview" if prov[0] == "gemini" else "gpt-5.4-mini")
    print(f"model: {prov[0]} / {model}", flush=True)
    for size in (10, 4, 1):  # מה שנשמט במנה גדולה עובר שוב במנות קטנות
        todo = [m["i"] for m in meta if m["i"] not in cache]
        if not todo:
            break
        batches = [todo[k:k + size] for k in range(0, len(todo), size)]
        print(f"classify: {len(todo)} images, batch {size}", flush=True)
        done = 0
        try:
            with ThreadPoolExecutor(args.workers) as ex:
                for res in ex.map(lambda b: classify_batch(prov, model, run, b), batches):
                    cache.update(res); done += 1
                    if done % 10 == 0:
                        print(f"  {min(done * size, len(todo))}/{len(todo)}", flush=True)
                        cache_f.write_text(json.dumps(cache, ensure_ascii=False))
        except Fatal as e:
            cache_f.write_text(json.dumps(cache, ensure_ascii=False))
            raise SystemExit(f"עצרתי: {e} (סווגו עד עכשיו {len(cache)} מתוך {len(meta)})")
        cache_f.write_text(json.dumps(cache, ensure_ascii=False))

    # 2. חדות, חתימות ושיבוץ ראשוני
    for m in meta:
        p = run / "cls" / f"{m['i']:05d}.jpg"
        g = cache.get(m["i"], {})
        m["sharp"] = sharpness(p)
        m["dh"] = dhash(p)
        m["cat"] = g.get("cat") if g.get("cat") in CATS else "other"
        m["tag"] = g.get("tag", "")
        m["sensitive"] = bool(g.get("sensitive"))
        m["blurry"] = bool(g.get("blurry")) and m["sharp"] < 120
        m["accidental"] = bool(g.get("accidental"))
        if m.get("kind") == "video":  # תמונה אחת מטושטשת לא אומרת שהסרטון מטושטש
            m["blurry"] = False
            m["accidental"] = m["accidental"] and (m.get("duration") or 0) < 3
        m["ai"] = bool(m.get("ai_meta")) or bool(g.get("ai_generated"))
        m["people"] = [p for p in (g.get("people") or []) if p in PEOPLE]
        m["ts"] = datetime.fromisoformat(m["date"]).timestamp()

    # 3. כפולות: בודקים רק שכנים בזמן (מהיר גם ל-10,000 תמונות). החדה בכל קבוצה נשארת
    by_time = sorted(meta, key=lambda m: m["ts"])
    keep_of = {}
    for k, a in enumerate(by_time):
        for b in by_time[k + 1:]:
            if b["ts"] - a["ts"] > 600:
                break
            if a.get("kind", "image") != b.get("kind", "image"):
                continue
            lim = 1 if (a["screenshot"] or b["screenshot"]) else 4  # צילומי מסך של אותה אפליקציה דומים גם כשהם שונים
            if bin(a["dh"] ^ b["dh"]).count("1") <= lim:
                ra, rb = keep_of.get(a["i"], a["i"]), keep_of.get(b["i"], b["i"])
                if ra == rb:
                    continue
                best = max((ra, rb), key=lambda i: meta[i]["sharp"])
                worse = rb if best == ra else ra
                for x, r in list(keep_of.items()):
                    if r == worse:
                        keep_of[x] = best
                keep_of[worse] = best
    for m in meta:
        m["dup_of"] = keep_of.get(m["i"])

    # 4. טיולים לפי GPS: בית = התא (בערך 50 ק"מ) עם הכי הרבה תמונות
    geo = [m for m in meta if m.get("lat") is not None]
    trip_of = {}
    if len(geo) >= 10:
        cells = Counter((round(m["lat"] * 2) / 2, round(m["lon"] * 2) / 2) for m in geo)
        home = cells.most_common(1)[0][0]
        away = sorted([m for m in geo if km((m["lat"], m["lon"]), home) > 80], key=lambda m: m["ts"])
        groups, cur = [], []
        for m in away:  # פער של יותר משלושה ימים = טיול חדש
            if cur and m["ts"] - cur[-1]["ts"] > 3 * 86400:
                groups.append(cur); cur = []
            cur.append(m)
        if cur:
            groups.append(cur)
        names = Counter()
        for g in groups:
            if len(g) < 8:
                for m in g:
                    trip_of[m["i"]] = "*"
                continue
            d = datetime.fromtimestamp(g[len(g) // 2]["ts"])
            name = f"{HEB_MONTHS[d.month - 1]} {d.year}"
            names[name] += 1
            if names[name] > 1:
                name += f" ({names[name]})"
            for m in g:
                trip_of[m["i"]] = name
        print("home cell:", home, "| trips:", sorted(set(trip_of.values())))
    for m in meta:
        m["trip"] = trip_of.get(m["i"]) or ("*" if m["cat"] == "trip" else None)

    # 5. שיבוץ סופי
    for m in meta:
        if m["dup_of"] is not None:
            m["album"] = "dupes"
        elif m["blurry"] or m["accidental"]:
            m["album"] = "blurry"
        elif m["ai"]:
            m["album"] = "ai"
        elif m["trip"]:
            m["album"] = "trip" if m["trip"] == "*" else "trip:" + m["trip"]
        else:
            m["album"] = "receipt" if m["cat"] == "docs" else m["cat"]
        m.pop("dh", None)
    (run / "sorted.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    c = Counter(m["album"] for m in meta)
    for k, v in c.most_common():
        print(f"{v:6d}  {k}")
    freed = sum(m.get("bytes") or 0 for m in meta if m["album"] in ("dupes", "blurry"))
    print(f"review before delete: {c['dupes'] + c['blurry']} items, {freed / 1e6:.0f}MB")
    pc = Counter(p for m in meta for p in m["people"])
    if pc:
        print("people:", ", ".join(f"{k} {v}" for k, v in pc.most_common()))


if __name__ == "__main__":
    main()
