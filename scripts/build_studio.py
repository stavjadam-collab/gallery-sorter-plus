"""שלב 3: הממשק המונפש. קיר של כל התמונות, כפתור אחד, והן עפות לאלבומים.

יוצר RUN/studio/index.html שנפתח בדפדפן (בלי שרת). מצלמים את המסך, ויש סרטון.
עד 1,200 תמונות נכנסות לממשק (דגימה אקראית כשיש יותר), כדי שהוא ירוץ חלק בכל מחשב.
המונים מציגים את המספרים של כל הגלריה: כל אריח מייצג אז כמה תמונות.
תמונות שהמודל סימן כרגישות (תעודות, פרטי בנק, שיחות פרטיות) מטושטשות בממשק, כך ששום פרט לא נראה במצלמה.

  python scripts/build_studio.py --run RUN [--title "הגלריה שלי"]
"""
import argparse
import json
import random
import shutil
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageFilter

from common import album_name

HERE = Path(__file__).resolve().parent.parent
TILE, COLS, MAX = 160, 40, 1200
MAX_CARDS = 13  # מעבר לזה הכרטיסים צפופים מדי למסך אחד


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--title", default="הגלריה שלי")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    run = Path(args.run).expanduser()
    meta = json.loads((run / "sorted.json").read_text(encoding="utf-8"))
    total_all = len(meta)
    if len(meta) > MAX:
        random.Random(7).shuffle(meta)
        meta = meta[:MAX]
    meta.sort(key=lambda m: m["date"])  # הישנה למעלה, החדשה למטה, כמו בגלריה

    # אלבומים קטנים מדי מצטרפים ל"שונות"; טיולים קטנים ל"טיולים"
    sizes = Counter(m["album"] for m in meta)
    for m in meta:
        a = m["album"]
        if a.startswith("trip:") and sizes[a] < 10:
            m["viz"] = "trip"
        elif a not in ("dupes", "blurry") and not a.startswith("trip") and sizes[a] < 6:
            m["viz"] = "other"
        else:
            m["viz"] = a
    sizes = Counter(m["viz"] for m in meta)
    keep = [a for a, _ in sizes.most_common() if a not in ("dupes", "blurry")]
    if len(keep) > MAX_CARDS:
        spill = set(keep[MAX_CARDS - 1:])
        for m in meta:
            if m["viz"] in spill:
                m["viz"] = "other"
        sizes = Counter(m["viz"] for m in meta)
        keep = [a for a, _ in sizes.most_common() if a not in ("dupes", "blurry")]
    review = [a for a in ("dupes", "blurry") if sizes.get(a)]
    if len(review) == 2:  # בממשק כרטיס בדיקה אחד
        for m in meta:
            if m["viz"] == "blurry":
                m["viz"] = "dupes"
        review = ["dupes"]
        sizes = Counter(m["viz"] for m in meta)
    albums = [{"id": a, "name": album_name(a), "kind": "keep", "n": sizes[a]} for a in keep]
    albums += [{"id": a, "name": "כפולות ומטושטשות" if a == "dupes" else album_name(a), "kind": "del", "n": sizes[a]} for a in review]

    out = run / "studio"
    out.mkdir(exist_ok=True)
    rows = (len(meta) + COLS - 1) // COLS
    atlas = Image.new("RGB", (COLS * TILE, rows * TILE), (10, 18, 38))
    for k, m in enumerate(meta):
        im = Image.open(run / "thumbs" / f"{m['i']:05d}.jpg").convert("RGB").resize((TILE, TILE), Image.LANCZOS)
        if m.get("sensitive"):
            im = im.filter(ImageFilter.GaussianBlur(18))
        atlas.paste(im, ((k % COLS) * TILE, (k // COLS) * TILE))
    atlas.save(out / "atlas.jpg", quality=82)

    items = [{"i": k, "a": m["viz"], "tag": m.get("tag", ""), "mb": round((m.get("bytes") or 0) / 1e6, 2),
              "s": 1 if m.get("sensitive") else 0} for k, m in enumerate(meta)]
    # תמונות הפתיחה שנבדקות בגדול: אחת מכל אחד מהאלבומים הגדולים, ואחת מהכפולות
    intro = [a["id"] for a in albums if a["kind"] == "keep"][:5] + review[:1]
    n = len(meta)
    sub = f"{total_all:,} תמונות"
    data = {"cols": COLS, "tile": TILE, "albums": albums, "items": items, "total": n, "intro": intro,
            "eyebrow": args.title, "sub": sub, "displayTotal": total_all,
            "freedMB": round(sum(x["mb"] for x in items if x["a"] in review), 1)}
    (out / "data.js").write_text("window.SORT_DATA=" + json.dumps(data, ensure_ascii=False) + ";", encoding="utf-8")
    shutil.copy(HERE / "studio" / "studio.html", out / "index.html")
    shutil.copy(HERE / "studio" / "logo.png", out / "logo.png")
    print("albums:")
    for a in albums:
        print(f"  {a['n']:5d}  {a['name']}")
    page = (out / "index.html").resolve()
    print("->", page)
    if not args.no_open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
