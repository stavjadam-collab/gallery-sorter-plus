"""שלב 1: איסוף התמונות והסרטונים לתיקיית עבודה.

שני מקורות:
  --folder PATH    כל תיקייה במחשב: תמונות מאייפון או מאנדרואיד שהועתקו בכבל, תיקיית iCloud Photos
                   בווינדוס, כונן גיבוי. גם קובצי ה-zip של Google Takeout, כמו שהורדו, בלי לחלץ:
                   מצביעים על התיקייה שבה הם יושבים (או על קובץ zip אחד), והסקריפט מחלץ רק את מה שצריך.
  --mac-photos     ספריית התמונות של המק (אייפון עם תמונות iCloud). דורש: pip install osxphotos

חדש בגרסה הזו:
  * סרטונים: לכל סרטון נשלפת תמונה אחת מהאמצע לסיווג. הסרטון עצמו מועתק בסוף לאלבום שלו.
    לדלג על סרטונים: --no-videos
  * סימון AI: תמונות שנוצרו במחולל (Gemini, ChatGPT, Midjourney, Stable Diffusion ועוד) מזוהות
    כבר כאן לפי סימנים בקובץ עצמו (IPTC/C2PA, שדות טקסט של PNG, שם הקובץ). המודל משלים את השאר בשלב 2.

לכל פריט נשמרים שני עותקים מוקטנים בלבד (384px לסיווג, 160px לממשק). המקור לא זז ולא משתנה.

  python scripts/gather.py --folder ~/Pictures/phone --n 1000 --out ~/.gallery-sorter/runs/run1
  python scripts/gather.py --mac-photos --n 1000 --out ~/.gallery-sorter/runs/run1
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

import common  # noqa: F401  (קידוד פלט בטוח בווינדוס)

register_heif_opener()
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".avi", ".mkv"}
SHOT_RE = re.compile(r"screenshot|screen shot|צילום מסך|scr_|screenshot_", re.I)

# סימני AI בתוך הקובץ. "compositeWith..." (תמונה אמיתית שנערכה ב-AI) לא נחשב.
AI_NAME_RE = re.compile(r"gemini_generated|dall[\s_\-·]?e|chatgpt image|midjourney|^mj_|firefly|leonardo|ideogram|"
                        r"stable[\s_\-]?diffusion|comfyui|^flux|imagen|grok[\s_\-]?image|^aigen|nano[\s_\-]?banana", re.I)
AI_SOFTWARE_RE = re.compile(rb"(Google Gemini|Imagen|DALL.?E|ChatGPT|OpenAI|Midjourney|Adobe Firefly|"
                            rb"Stable Diffusion|ComfyUI|NovelAI|Leonardo|Ideogram|Grok)", re.I)


def ai_marks(path):
    """מחזיר סיבה קצרה אם יש בקובץ סימן לכך שנוצר ב-AI, אחרת None. קורא רק את ההתחלה והסוף של הקובץ."""
    if AI_NAME_RE.search(path.name):
        return "שם הקובץ"
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(512 * 1024)
            tail = b""
            if size > 512 * 1024:
                f.seek(max(size - 128 * 1024, 512 * 1024))
                tail = f.read()
    except OSError:
        return None
    blob = head + tail
    if b"digitalsourcetype/trainedAlgorithmicMedia" in blob or b"digitalSourceType/trainedAlgorithmicMedia" in blob:
        return "חתימת IPTC/C2PA"
    if path.suffix.lower() == ".png" and (b"tEXtparameters" in blob or b"tEXtprompt" in blob or b"iTXtparameters" in blob):
        return "פרומפט בתוך ה-PNG"
    m = AI_SOFTWARE_RE.search(blob[:64 * 1024])
    if m:
        return "תוכנת יצירה: " + m.group(1).decode(errors="ignore")
    return None


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        return which("ffmpeg")


ISO6709 = re.compile(r"location\s*:\s*([+-]\d+\.\d+)([+-]\d+\.\d+)")


def video_info(path, ff):
    """תאריך, מיקום ואורך מתוך הכותרות של הסרטון (בעזרת הפלט של ffmpeg)."""
    date = lat = lon = None
    dur = 0.0
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=60)
        err = r.stderr
        m = re.search(r"creation_time\s*:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", err)
        if m:
            date = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            if date.year < 2000:
                date = None
        m = ISO6709.search(err)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
        if m:
            dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return date, lat, lon, dur


def video_frame(path, ff, dur, tmp):
    """תמונה אחת מאמצע הסרטון."""
    t = max(0.0, min(dur / 2, dur - 0.2)) if dur else 1.0
    subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                    "-vf", "scale=768:-2", str(tmp)], capture_output=True, timeout=120)
    if not tmp.exists() and t > 0:
        subprocess.run([ff, "-v", "error", "-y", "-i", str(path), "-frames:v", "1", "-vf", "scale=768:-2", str(tmp)],
                       capture_output=True, timeout=120)
    return Image.open(tmp) if tmp.exists() else None


def exif_info(im):
    """תאריך צילום ו-GPS מתוך EXIF, אם יש."""
    date = lat = lon = None
    camera = False
    try:
        ex = im.getexif()
        camera = bool(ex.get(271) or ex.get(272))  # יצרן/דגם מצלמה: מבדיל צילום אמיתי מצילום מסך
        sub = ex.get_ifd(0x8769)
        raw = sub.get(36867) or sub.get(36868) or ex.get(306)
        if raw:
            date = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
        gps = ex.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            def deg(v):
                d, m, s = [float(x) for x in v]
                return d + m / 60 + s / 3600
            lat, lon = deg(gps[2]), deg(gps[4])
            if gps.get(1) == "S":
                lat = -lat
            if gps.get(3) == "W":
                lon = -lon
            if abs(lat) < 1e-6 and abs(lon) < 1e-6:
                lat = lon = None
    except Exception:
        pass
    return date, lat, lon, camera


_JSON_INDEX = {}


def _jsons_in(d):
    if d not in _JSON_INDEX:
        _JSON_INDEX[d] = [f for f in os.listdir(d) if f.lower().endswith(".json")]
    return _JSON_INDEX[d]


def sidecar_for(path):
    """Google Takeout שם ליד כל תמונה json עם תאריך ומיקום. השם משתנה בין גרסאות, ונחתך ב-51 תווים:
    IMG_1.jpg.json, IMG_1.jpg.supplemental-metadata.json, IMG_1.jpg.supplemental-me.json,
    ולכפילויות: IMG_1(1).jpg ← IMG_1.jpg(1).json או IMG_1.jpg.supplemental-metadata(1).json."""
    name, d = path.name, str(path.parent)
    files = _jsons_in(d)
    m = re.match(r"^(.*)\((\d+)\)(\.[^.]+)$", name)
    if m:
        base, n = m.group(1) + m.group(3), m.group(2)
        for f in (f"{base}({n}).json", f"{base}.supplemental-metadata({n}).json"):
            if f in files:
                return path.with_name(f)
    full = name + ".supplemental-metadata"
    best = None
    for f in files:
        stem = f[:-5]
        if stem == name or (full.startswith(stem) and len(stem) >= min(len(name), 40)):
            if best is None or len(f) > len(best):
                best = f
    if best:
        return path.with_name(best)
    alt = path.with_suffix(".json")
    return alt if alt.name in files else None


def takeout_sidecar(path):
    cand = sidecar_for(path)
    if cand:
        try:
            j = json.loads(cand.read_text(encoding="utf-8"))
            ts = int(j.get("photoTakenTime", {}).get("timestamp", 0))
            geo = j.get("geoData") or {}
            lat, lon = geo.get("latitude"), geo.get("longitude")
            if not lat and not lon:
                lat = lon = None
            return (datetime.fromtimestamp(ts, timezone.utc) if ts else None), lat, lon
        except Exception:
            pass
    return None, None, None


def unzip_takeout(zips, dest, videos=True):
    """מחלץ מכל zip תמונות, סרטונים (אם רוצים) וקובצי json, לתוך תיקיית ההרצה. הרצה חוזרת לא מחלצת שוב."""
    dest.mkdir(parents=True, exist_ok=True)
    want = IMAGE_EXT | (VIDEO_EXT if videos else set()) | {".json"}
    n = 0
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for info in zf.infolist():
                ext = Path(info.filename).suffix.lower()
                if info.is_dir() or ext not in want:
                    continue
                target = dest / z.stem / info.filename
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as out:
                        while True:
                            chunk = src.read(8 * 1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    try:  # תאריך הקובץ מתוך ה-zip, לגיבוי כשאין לתמונה json
                        ts = datetime(*info.date_time).timestamp()
                        os.utime(target, (ts, ts))
                    except (ValueError, OSError):
                        pass
                n += ext != ".json"
        print(f"unzipped {z.name}", flush=True)
    print(f"{n} files from {len(zips)} zip file(s)", flush=True)
    return dest


def scan(root, skip, exts):
    return [p for p in root.rglob("*")
            if p.suffix.lower() in exts and p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(root).parts)
            and not any(s == q for s in skip for q in p.resolve().parents)]


def from_folder(root, n, skip, out, videos=True):
    root = Path(root).expanduser().resolve()
    if not root.exists():
        sys.exit(f"לא נמצא: {root}")
    exts = IMAGE_EXT | (VIDEO_EXT if videos else set())
    ff = ffmpeg_exe() if videos else None
    if videos and not ff:
        print("אין ffmpeg: מדלג על סרטונים (pip install imageio-ffmpeg פותר את זה)", flush=True)
        exts, videos = IMAGE_EXT, False
    skip = [Path(s).expanduser().resolve() for s in skip]
    zips = [root] if root.suffix.lower() == ".zip" else (sorted(root.glob("*.zip")) if root.is_dir() else [])
    files = scan(root, skip, exts) if root.is_dir() else []
    if zips:
        files += scan(unzip_takeout(zips, out / "unzipped", videos), [], exts)
    nv = sum(p.suffix.lower() in VIDEO_EXT for p in files)
    print(f"found {len(files) - nv} images and {nv} videos in {root}", flush=True)
    if not files:
        sys.exit("לא נמצאו תמונות. בדקו שהתיקייה נכונה (ושקובצי ה-zip הורדו עד הסוף).")
    items = []
    for p in files:
        try:
            tdate, tlat, tlon = takeout_sidecar(p)
            if p.suffix.lower() in VIDEO_EXT:
                date, lat, lon, dur = video_info(p, ff)
                it = {"kind": "video", "duration": round(dur, 1), "screenshot": False}
            else:
                date, lat, lon, camera = exif_info(Image.open(p))
                shot = bool(SHOT_RE.search(p.name)) or (p.suffix.lower() == ".png" and not camera)
                it = {"kind": "image", "screenshot": shot}
            date = date or tdate or datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if lat is None and tlat is not None:
                lat, lon = tlat, tlon
            it.update({"src": str(p), "date": date, "lat": lat, "lon": lon,
                       "bytes": p.stat().st_size, "filename": p.name, "ai_meta": ai_marks(p)})
            items.append(it)
        except Exception as e:
            print("skip", p.name, e)
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:n]


def from_mac_photos(n, library, videos=True):
    try:
        import osxphotos
    except ImportError:
        sys.exit("חסר osxphotos. התקינו: pip install osxphotos")
    lib = Path(library or "~/Pictures/Photos Library.photoslibrary").expanduser()
    # נתיב מפורש לבסיס הנתונים: בלעדיו osxphotos מנסה לקרוא העדפה מוגנת של Photos ונתקע על הרשאות
    db = osxphotos.PhotosDB(dbfile=str(lib / "database" / "Photos.sqlite"))
    photos = [p for p in db.photos(images=True, movies=videos) if p.date and not p.hidden]
    photos.sort(key=lambda p: p.date, reverse=True)
    items, cloud_only = [], 0
    for p in photos:
        if len(items) >= n * 1.1:
            break
        if p.ismovie:
            src = p.path if p.path and os.path.exists(p.path) else None
        else:
            cands = [d for d in (p.path_derivatives or []) if d and os.path.exists(d)]
            src = max(cands, key=os.path.getsize) if cands else (p.path if p.path and os.path.exists(p.path) else None)
        if not src:
            cloud_only += 1  # יושב רק ב-iCloud ואין לו עותק במק
            continue
        lat, lon = p.location if p.location else (None, None)
        items.append({"src": src, "date": p.date.astimezone(timezone.utc), "lat": lat, "lon": lon,
                      "screenshot": bool(p.screenshot), "bytes": p.original_filesize,
                      "filename": p.original_filename, "uuid": p.uuid,
                      "kind": "video" if p.ismovie else "image",
                      "duration": round(float(getattr(p, "duration", 0) or 0), 1),
                      "ai_meta": ai_marks(Path(src))})
    print(f"Photos library: {len(photos)} items, using the newest {min(n, len(items))}"
          + (f" ({cloud_only} skipped: only in iCloud, no copy on this Mac)" if cloud_only else ""), flush=True)
    return items[:n]


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--folder")
    g.add_argument("--mac-photos", action="store_true")
    ap.add_argument("--library", help="נתיב לספריית תמונות אחרת במק")
    ap.add_argument("--n", type=int, default=1000, help="כמה פריטים (האחרונים קודם)")
    ap.add_argument("--no-videos", action="store_true", help="רק תמונות")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    videos = not args.no_videos
    out = Path(args.out).expanduser()
    (out / "cls").mkdir(parents=True, exist_ok=True)
    (out / "thumbs").mkdir(parents=True, exist_ok=True)
    tmp = out / "frame.jpg"

    items = (from_mac_photos(args.n, args.library, videos) if args.mac_photos
             else from_folder(args.folder, args.n, [out], out, videos))
    ff = ffmpeg_exe() if any(it.get("kind") == "video" for it in items) else None
    meta = []
    for it in items:
        try:
            if it.get("kind") == "video":
                tmp.unlink(missing_ok=True)
                im = video_frame(Path(it["src"]), ff, it.get("duration") or 0, tmp) if ff else None
                if im is None:
                    raise ValueError("no frame")
                im = im.convert("RGB")
            else:
                im = ImageOps.exif_transpose(Image.open(it["src"])).convert("RGB")
        except Exception as e:
            print("skip", it["filename"], e)
            continue
        i = len(meta)
        c = im.copy(); c.thumbnail((384, 384)); c.save(out / "cls" / f"{i:05d}.jpg", quality=82)
        ImageOps.fit(im, (160, 160)).save(out / "thumbs" / f"{i:05d}.jpg", quality=80)
        meta.append({**it, "i": i, "date": it["date"].isoformat(), "w": im.width, "h": im.height})
        if i % 100 == 0:
            print(i, it["date"].date(), flush=True)
    tmp.unlink(missing_ok=True)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    nv = sum(m.get("kind") == "video" for m in meta)
    na = sum(1 for m in meta if m.get("ai_meta"))
    print(f"done: {len(meta) - nv} images, {nv} videos ({na} marked as AI by the file itself) -> {out}")


if __name__ == "__main__":
    main()
