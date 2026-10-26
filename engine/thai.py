"""Thai text helpers: tokenisation, phrase chunking, filler/keyword detection, spell flags."""
import re
import unicodedata
from functools import lru_cache

try:
    from pythainlp.tokenize import word_tokenize as _wt
    from pythainlp.corpus import thai_words, thai_stopwords
    HAVE_PYTHAINLP = True
except Exception:  # pragma: no cover - degraded mode
    HAVE_PYTHAINLP = False

# Thai combining marks take no horizontal space of their own.
_COMBINING = set("ัิีึืฺุู็่้๊๋์ํ๎")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

FILLERS = {"เอ่อ", "เออ", "อ่า", "อ้า", "อืม", "อึม", "อือ", "เอิ่ม", "อ่ะ", "เอ่ออ", "แบบว่า", "คือแบบ", "อะ", "เอ้อ",
           "um", "uh", "erm", "hmm"}
NUMBER_WORDS = {"ร้อย", "พัน", "หมื่น", "แสน", "ล้าน", "พันล้าน", "เปอร์เซ็นต์", "เท่า", "ครึ่ง"}
UNIT_WORDS = {"คน", "ปี", "บาท", "ล้าน", "พัน", "หมื่น", "แสน", "เปอร์เซ็นต์", "%", "เท่า", "วัน", "เดือน", "ชั่วโมง",
              "นาที", "กิโลเมตร", "กิโล", "เมตร", "ครั้ง", "ประเทศ", "หลัง", "ตัว", "ชิ้น", "ดอลลาร์", "ล้านคน", "ราย", "ศพ"}

ROLE_CUES = {
    "hook": ["รู้ไหม", "รู้หรือไม่", "เคยสงสัย", "เชื่อไหม", "ลองนึก", "ถ้าบอกว่า", "ไม่น่าเชื่อ"],
    "turn": ["แต่", "ทว่า", "อย่างไรก็ตาม", "จู่ๆ", "ปรากฏว่า", "สิ่งที่น่าแปลก", "แต่แล้ว", "กลับ", "พลิก", "ที่น่าตกใจ"],
    "example": ["ยกตัวอย่าง", "ตัวอย่างเช่น", "อย่างเช่น", "เช่น", "ลองดู"],
    "steps": ["ขั้นแรก", "ขั้นที่", "อย่างแรก", "ข้อแรก", "ข้อที่", "ขั้นตอน", "ขั้นสุดท้าย", "อันดับแรก", "ประการแรก"],
    "conclusion": ["สรุป", "สุดท้ายนี้", "ท้ายที่สุด", "คอมเมนต์", "กดติดตาม", "กดไลก์", "แชร์", "ฝากติดตาม"],
    "compare": ["เทียบกับ", "เปรียบเทียบ", "ในขณะที่", "ต่างจาก", "กับ", "vs"],
    "mystery": ["ลึกลับ", "ปริศนา", "หายไป", "หายตัว", "น่ากลัว", "ความมืด", "ตอนกลางคืน", "ในคืน", "ไร้ร่องรอย",
                "ผี", "สยอง", "ไม่มีใครอธิบาย", "เงียบสงัด", "ทิ้งไว้"],
}
STEP_MARKERS = ["ขั้นแรก", "ขั้นที่สอง", "ขั้นที่สาม", "ขั้นที่สี่", "ขั้นสุดท้าย", "อย่างแรก", "อย่างที่สอง", "อย่างที่สาม",
                "ข้อแรก", "ข้อที่สอง", "ข้อที่สาม", "อันดับแรก", "ต่อมา", "สุดท้าย", "ขั้นที่ 1", "ขั้นที่ 2", "ขั้นที่ 3"]


def visual_len(s: str) -> int:
    return sum(1 for c in s if c not in _COMBINING and not unicodedata.category(c).startswith("M"))


def normalize(s: str) -> str:
    s = s.translate(_THAI_DIGITS).lower()
    return re.sub(r"[\s\.,!?\"'“”‘’…\-–—:;()\[\]]+", "", s)


@lru_cache(maxsize=4096)
def _tok(text: str):
    if HAVE_PYTHAINLP:
        return tuple(_wt(text, engine="newmm", keep_whitespace=True))
    return tuple(re.findall(r"\s+|\S+", text))


def tokenize(text: str):
    """Return tokens; whitespace runs are returned as ' ' tokens (phrase boundaries in Thai)."""
    out = []
    for t in _tok(text):
        if t.isspace():
            if out and out[-1] != " ":
                out.append(" ")
        elif t:
            # newmm splits numbers like 1,930 / 30% into pieces; glue digits back together
            if out and re.fullmatch(r"[\d,\.%]+", t) and re.fullmatch(r"[\d,\.]+", out[-1]):
                out[-1] += t
            else:
                out.append(t)
    while out and out[-1] == " ":
        out.pop()
    while out and out[0] == " ":
        out.pop(0)
    return out


def is_number(tok: str) -> bool:
    t = tok.translate(_THAI_DIGITS)
    return bool(re.fullmatch(r"\d[\d,\.]*%?", t)) or tok in NUMBER_WORDS


def is_filler(tok: str) -> bool:
    return normalize(tok) in FILLERS


def content_words(tokens):
    stop = thai_stopwords() if HAVE_PYTHAINLP else set()
    return [t for t in tokens if t != " " and t not in stop and not is_filler(t) and visual_len(t) >= 2]


def has_cue(text: str, role: str) -> bool:
    n = text.replace(" ", "")
    return any(c.replace(" ", "") in n for c in ROLE_CUES[role])


def starts_with_cue(text: str, role: str) -> bool:
    n = text.strip().replace(" ", "")
    return any(n.startswith(c.replace(" ", "")) for c in ROLE_CUES[role])


def pick_keywords(tokens, doc_freq, max_n=1):
    """Pick the strongest words to highlight: numbers first, then rare-but-repeated content words."""
    stop = thai_stopwords() if HAVE_PYTHAINLP else set()
    scored = []
    for i, t in enumerate(tokens):
        if t == " " or t in stop or is_filler(t):
            continue
        if is_number(t):
            scored.append((100 + visual_len(t), i))
            continue
        vl = visual_len(t)
        if vl < 3:
            continue
        cue_bonus = 8 if any(t in c or c in t for c in ROLE_CUES["mystery"]) else 0
        scored.append((vl + 3 * min(doc_freq.get(t, 1), 3) + cue_bonus, i))
    scored.sort(reverse=True)
    return sorted(i for _, i in scored[:max_n])


def chunk_phrases(tokens, max_chars=16, min_chars=4):
    """Split tokens into readable one-line phrases. Prefers breaking at spaces, then word boundaries.

    Returns list of (start_idx, end_idx_exclusive) into tokens.
    """
    phrases, cur_start, cur_len = [], 0, 0
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        tl = visual_len(t) if t != " " else 0
        if t == " ":
            if cur_len >= min_chars:
                phrases.append((cur_start, i))
                cur_start, cur_len = i + 1, 0
            i += 1
            continue
        if cur_len and cur_len + tl > max_chars:
            phrases.append((cur_start, i))
            cur_start, cur_len = i, 0
        cur_len += tl
        i += 1
    if cur_start < n:
        if phrases and cur_len < min_chars and visual_len("".join(tokens[phrases[-1][0]:n])) <= max_chars + 4:
            phrases[-1] = (phrases[-1][0], n)
        else:
            phrases.append((cur_start, n))
    # strip leading/trailing spaces from each phrase
    out = []
    for a, b in phrases:
        while a < b and tokens[a] == " ":
            a += 1
        while b > a and tokens[b - 1] == " ":
            b -= 1
        if b > a:
            out.append((a, b))
    return out


EXTRA_WORDS = {"แอป", "แอพ", "เพจ", "คอนเทนต์", "แคมเปญ", "ติ๊กต็อก", "ไลก์", "ไลค์", "แชร์", "คอมเมนต์", "โพสต์", "ฟีด",
               "รีล", "สตอรี่", "อินฟลูเอนเซอร์", "แบรนด์", "ออนไลน์", "ยูทูบ", "เฟซบุ๊ก", "อินสตาแกรม", "แพลตฟอร์ม",
               "ไลฟ์", "ครีเอเตอร์", "แฮชแท็ก", "อัลกอริทึม", "เอนเกจเมนต์", "คลิป", "ซับ"}


def _user_words():
    from . import DATA_DIR
    p = DATA_DIR / "custom_words.txt"
    return set(w.strip() for w in p.read_text(encoding="utf-8").splitlines() if w.strip()) if p.exists() else set()


def unknown_words(text: str):
    """Words worth a human look before export: not in the Thai dictionary, or a run of 3+ tiny
    fragments (newmm shreds unknown names / mis-heard words into single syllables)."""
    if not HAVE_PYTHAINLP:
        return []
    words = set(thai_words()) | EXTRA_WORDS | _user_words()
    flagged, run = [], []

    def flush():
        if len(run) >= 2 and "".join(run) not in words and any(r not in words for r in run):
            flagged.append("".join(run))
        elif len(run) == 1 and run[0] not in words:
            flagged.append(run[0])
        run.clear()

    for t in tokenize(text):
        thai = bool(re.search(r"[\u0e00-\u0e7f]", t))
        if t == " " or is_number(t) or not thai or t in FILLERS:
            flush()
            continue
        if run and t in words and visual_len(t) > 2:
            flush()
        if visual_len(t) <= 2 or (run and t not in words):
            run.append(t)
            continue
        flush()
        if t not in words:
            flagged.append(t)
    flush()
    return list(dict.fromkeys(flagged))


def key_clause(text: str, keywords=(), max_chars=22):
    """The most informative space-separated clause (verbatim) — for title cards that don't just repeat the
    opening subtitle. Skips attention cues like 'รู้ไหมว่า'."""
    best, score = "", -1
    for chunk in [c for c in text.split(" ") if c.strip()]:
        c = chunk.strip()
        if any(c.replace(" ", "").startswith(q) for q in ROLE_CUES["hook"]) and visual_len(c) < 12:
            continue
        for lead in ("ที่", "ซึ่ง", "และ", "แต่"):
            if c.startswith(lead) and visual_len(c) > len(lead) + 4:
                c = c[len(lead):]
        if visual_len(c) > max_chars:
            c = short_title(c, max_chars)
        sc = sum(3 for k in keywords if k and k in c) + min(visual_len(c), max_chars) / 4
        if sc > score:
            best, score = c, sc
    return best or short_title(text, max_chars)


def short_title(text: str, max_chars=22):
    """A short title-card line taken verbatim from what was said (never invented)."""
    toks = tokenize(text)
    out, ln = [], 0
    for t in toks:
        tl = visual_len(t)
        if t == " " and ln >= 8:
            break
        if ln + tl > max_chars:
            break
        out.append(t)
        ln += tl
    return "".join(out).strip()
