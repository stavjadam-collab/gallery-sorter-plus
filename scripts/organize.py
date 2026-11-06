"""שלב 4: מסדר את התמונות והסרטונים בתיקיות, ובונה דף חיפוש. מעתיק בלבד: המקור לא זז, לא משתנה ולא נמחק.

  python scripts/organize.py --run RUN                       # תוכנית: כמה ייכנסו לכל תיקייה, בלי לגעת בכלום
  python scripts/organize.py --run RUN --dest "~/Pictures/מסדר הגלריה" --apply

התוצאה:
  <dest>/טיולים/...  <dest>/משפחה/...  <dest>/נוצר ב-AI/...  <dest>/קבלות ומסמכים/...
  <dest>/אנשים/<שם>/...                 (רק כשהוגדרו אנשים; עותק נוסף של כל תמונה שבה הם מופיעים)
  <dest>/לבדיקה לפני מחיקה/כפולות/...   <dest>/לבדיקה לפני מחיקה/מטושטשות/...
  <dest>/חיפוש בגלריה.html              דף אחד: מחפשים מילה ("קבלה", "חוף", שם של אדם) ורואים מיד
המחיקה עצמה, אם בכלל, נעשית ביד בטלפון או בגלריה, אחרי שעוברים על תיקיית הבדיקה.
"""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from common import PEOPLE_FOLDER, REVIEW_FOLDER, album_name
from search_page import build_search


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--dest", default=str(Path.home() / "Pictures" / "מסדר הגלריה"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-people-copies", action="store_true", help="בלי תיקיות אנשים (האנשים עדיין בחיפוש)")
    args = ap.parse_args()
    run, dest = Path(args.run).expanduser(), Path(args.dest).expanduser()
    meta = json.loads((run / "sorted.json").read_text(encoding="utf-8"))
    people_copies = not args.no_people_copies

    def folder(m):
        if m["album"] in ("dupes", "blurry"):
            return Path(REVIEW_FOLDER) / album_name(m["album"])
        return Path(album_name(m["album"]))

    plan = Counter(str(folder(m)) for m in meta)
    if people_copies:
        for m in meta:
            if m["album"] not in ("dupes", "blurry"):
                for p in m.get("people") or []:
                    plan[str(Path(PEOPLE_FOLDER) / p)] += 1
    nv = sum(m.get("kind") == "video" for m in meta)
    print(f"{'ייכנסו' if not args.apply else 'מעתיק'} {len(meta) - nv} תמונות ו-{nv} סרטונים אל {dest}:")
    for k, v in sorted(plan.items(), key=lambda kv: (kv[0].startswith(REVIEW_FOLDER), kv[0].startswith(PEOPLE_FOLDER), -kv[1])):
        print(f"  {v:6d}  {k}")
    if not args.apply:
        print("\nזו תוכנית בלבד. להעתקה בפועל: אותה פקודה עם --apply")
        return

    def copy_to(src, d, name):
        d.mkdir(parents=True, exist_ok=True)
        target = d / name
        k = 1
        while target.exists():  # שמות זהים מתיקיות שונות: מוסיפים מספר, לא דורסים
            target = d / f"{Path(name).stem} ({k}){Path(name).suffix}"
            k += 1
        shutil.copy2(src, target)
        return target

    copied = 0
    for m in meta:
        src = Path(m["src"])
        if not src.exists():
            print("missing", src)
            continue
        name = m.get("filename") or src.name
        if not Path(name).suffix:
            name += src.suffix
        t = copy_to(src, dest / folder(m), name)
        m["copy"] = str(t.relative_to(dest)).replace("\\", "/")
        if people_copies and m["album"] not in ("dupes", "blurry"):
            for p in m.get("people") or []:
                copy_to(src, dest / PEOPLE_FOLDER / p, name)
        copied += 1
        if copied % 200 == 0:
            print(f"  {copied}/{len(meta)}", flush=True)
    page = build_search(run, dest, meta)
    (run / "organized.json").write_text(json.dumps({"dest": str(dest), "copied": copied}, ensure_ascii=False))
    print(f"\nהועתקו {copied} פריטים אל {dest}. המקור לא נגע.")
    print(f"דף החיפוש: {page}")


if __name__ == "__main__":
    main()
