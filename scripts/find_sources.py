"""שלב 0: איפה התמונות? סורק את המקומות הנפוצים ומציע מקור, כדי שהמשתמש/ת לא יצטרכו לחפש.

  python scripts/find_sources.py

מוצא: ספריית Photos במק (אייפון עם iCloud), תיקיית iCloud Photos בווינדוס, קובצי Google Takeout
בהורדות, ותיקיות DCIM של טלפון או כרטיס זיכרון מחוברים. מדפיס לכל מקור את הפקודה המתאימה.
"""
import os
import platform
import string
from pathlib import Path

import common  # noqa: F401  (קידוד פלט בטוח בווינדוס)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
H = Path.home()


def count_images(d, cap=20000):
    n = 0
    for _, _, files in os.walk(d):
        n += sum(1 for f in files if Path(f).suffix.lower() in IMAGE_EXT)
        if n >= cap:
            return f"{cap:,}+"
    return f"{n:,}"


def main():
    found = []
    lib = H / "Pictures" / "Photos Library.photoslibrary"
    if platform.system() == "Darwin" and lib.exists():
        found.append(("ספריית Photos במק (אייפון עם תמונות iCloud)", "--mac-photos", "דורש: pip install osxphotos"))
    for d in (H / "Pictures" / "iCloud Photos" / "Photos", H / "Pictures" / "iCloud Photos",
              H / "iCloudPhotos", H / "Pictures" / "iCloudPhotos"):
        if d.is_dir():
            found.append((f"תיקיית iCloud Photos ({count_images(d)} תמונות)", f'--folder "{d}"', ""))
            break
    for d in (H / "Downloads", H / "Desktop"):
        zips = sorted(d.glob("takeout-*.zip")) if d.is_dir() else []
        if zips:
            size = sum(z.stat().st_size for z in zips)
            human = f"{size / 1e9:.1f}GB" if size >= 1e9 else f"{size / 1e6:.0f}MB"
            found.append((f"Google Takeout: {len(zips)} קובצי zip ב-{d.name} ({human})", f'--folder "{d}"',
                          f"לא צריך לחלץ. צריך בערך {human} פנויים, כי הסקיל מחלץ רק את התמונות"))
        for t in (d / "Takeout",) if d.is_dir() else ():
            if t.is_dir():
                found.append((f"תיקיית Takeout שחולצה ({count_images(t)} תמונות)", f'--folder "{t}"', ""))
    roots = [Path("/Volumes")] if platform.system() == "Darwin" else [Path(f"{c}:/") for c in string.ascii_uppercase if Path(f"{c}:/").exists()]
    for r in roots:
        try:
            vols = [r] if platform.system() != "Darwin" else [v for v in r.iterdir() if v.is_dir()]
        except OSError:
            continue
        for v in vols:
            dcim = v / "DCIM"
            if dcim.is_dir():
                found.append((f"תיקיית DCIM ב-{v} ({count_images(dcim)} תמונות)", f'--folder "{dcim}"', ""))
    if not found:
        print("לא מצאתי מקור תמונות במקומות הנפוצים.")
        print("אייפון/אנדרואיד בכבל: העתיקו את התמונות לתיקייה. Google Photos: takeout.google.com. ואז --folder <התיקייה>")
        return
    print("מקורות שמצאתי:")
    for k, (what, arg, note) in enumerate(found, 1):
        print(f"  {k}. {what}\n     gather.py {arg}" + (f"\n     ({note})" if note else ""))


if __name__ == "__main__":
    main()
