"""כלים משותפים: תיקיית הבית של הכלי, מפתחות, האלבומים (כולל אלבומים אישיים) והאנשים."""
import json
import os
import sys
from pathlib import Path

# ווינדוס: כשהפלט עובר בצינור (כמו אצל Claude Code) הקידוד הוא של האזור ולא UTF-8, והדפסה בעברית קורסת
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path(os.environ.get("GALLERY_SORTER_HOME", Path.home() / ".gallery-sorter"))
ENV_FILE = HOME / ".env"
ALBUMS_FILE = HOME / "albums.json"   # אלבומים אישיים (לא חובה)
PEOPLE_DIR = HOME / "people"          # people/<שם>/ עם 2-5 תמונות של כל אדם (לא חובה)

# מפתח: (שם התיקייה, תיאור למודל)
DEFAULT_ALBUMS = {
    "trip": ("טיולים", "טיול או חופשה: נוף מטייל, אתר תיירות, מלון, שדה תעופה, רחוב בעיר זרה"),
    "family": ("משפחה", "משפחה, ילדים, תינוקות, רגעים בבית"),
    "friends": ("חברים ואירועים", "חברים, אירועים, חתונות, ימי הולדת, מסיבות"),
    "food": ("אוכל", "אוכל, מסעדות, בתי קפה, משקאות"),
    "pets": ("חיות מחמד", "כלב, חתול או חיית מחמד אחרת"),
    "nature": ("נוף וטבע", "נוף וטבע קרוב לבית: שקיעה, ים, פארק, שמיים"),
    "work": ("עבודה", "עבודה: משרד, הרצאה, מצגת, צוות, לוח, מסך מחשב"),
    "receipt": ("קבלות ומסמכים", "קבלה, חשבונית, אישור תשלום, הזמנה, כרטיס טיסה"),
    "docs": ("קבלות ומסמכים", "צילום של מסמך נייר, תעודה, חוזה, פתק, לוח מודעות"),
    "saved": ("דברים ששמרתי", "צילום מסך של משהו שנשמר כדי לחזור אליו: מתכון, טיפ, פוסט, כתבה, רעיון, מוצר"),
    "screens": ("צילומי מסך", "צילום מסך אחר: שיחה, הגדרות, מפה, מסך אפליקציה"),
    "memes": ("ממים", "מם, בדיחה, תמונה מצחיקה מהרשת"),
    "shopping": ("קניות", "מוצר בחנות, קניות, השוואת מחירים"),
    "other": ("שונות", "שום דבר מהנ\"ל"),
}
SPECIAL_NAMES = {
    "ai": "נוצר ב-AI",
    "videos": "סרטונים",
    "dupes": "כפולות",
    "blurry": "מטושטשות",
}
REVIEW_FOLDER = "לבדיקה לפני מחיקה"
PEOPLE_FOLDER = "אנשים"
HEB_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def load_albums():
    """האלבומים בפועל: ברירת המחדל + מה שהמשתמש הוסיף ב-albums.json, פחות מה שביקש להוריד.

    albums.json לדוגמה:
      {"add": {"politics": {"name": "פוליטיקה", "desc": "הפגנות, שלטים, נאומים, צילומי מסך של חדשות"}},
       "remove": ["memes"],
       "rename": {"family": "המשפחה שלנו"}}
    """
    albums = dict(DEFAULT_ALBUMS)
    if ALBUMS_FILE.exists():
        cfg = json.loads(ALBUMS_FILE.read_text(encoding="utf-8"))
        for k in cfg.get("remove", []):
            if k != "other":
                albums.pop(k, None)
        for k, new in cfg.get("rename", {}).items():
            if k in albums:
                albums[k] = (new, albums[k][1])
        for k, v in cfg.get("add", {}).items():
            albums[k] = (v["name"], v.get("desc", v["name"]))
    return albums


def album_name(album_id):
    if album_id.startswith("trip:"):
        return "טיול · " + album_id[5:]
    if album_id in SPECIAL_NAMES:
        return SPECIAL_NAMES[album_id]
    a = load_albums().get(album_id)
    return a[0] if a else album_id


def people():
    """{שם: [נתיבי תמונות]} מתוך ~/.gallery-sorter/people/<שם>/"""
    out = {}
    if PEOPLE_DIR.exists():
        for d in sorted(PEOPLE_DIR.iterdir()):
            if d.is_dir():
                pics = sorted(p for p in d.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"})[:4]
                if pics:
                    out[d.name] = pics
    return out


def read_env():
    """מפתחות ממשתני סביבה או מ-~/.gallery-sorter/.env (שורות KEY=value)."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k].strip()
    return env


def provider():
    """Gemini אם יש מפתח (הכי זול), אחרת OpenAI. מחזיר (שם, מפתח)."""
    env = read_env()
    if env.get("GEMINI_API_KEY"):
        return "gemini", env["GEMINI_API_KEY"]
    if env.get("OPENAI_API_KEY"):
        return "openai", env["OPENAI_API_KEY"]
    raise SystemExit(f"חסר מפתח. שמרו בקובץ {ENV_FILE} שורה אחת: GEMINI_API_KEY=המפתח (או OPENAI_API_KEY=המפתח)")
