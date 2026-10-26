"""Content analysis: cut decisions (fillers, false starts, dead air) and story structure.

Cuts are decided per sentence from meaning first (filler-only, repeated take, low content);
silence is only trimmed *between and inside kept speech*, never used alone to drop a sentence.
"""
import difflib
import re
from collections import Counter

from . import thai

PACING = {  # max pause kept between phrases, pause kept after a dramatic beat, padding around speech
    "calm": {"max_pause": 0.70, "keep_pause": 0.35, "drama_pause": 0.70, "pre": 0.10, "post": 0.22},
    "normal": {"max_pause": 0.45, "keep_pause": 0.22, "drama_pause": 0.50, "pre": 0.08, "post": 0.18},
    "fast": {"max_pause": 0.30, "keep_pause": 0.14, "drama_pause": 0.35, "pre": 0.06, "post": 0.14},
}


def _real_words(seg):
    return [w for w in seg["words"] if w["w"] != " "]


def classify_cuts(segments, settings, log=print):
    """Annotate each segment with keep/cut_reason. Returns the list (mutated)."""
    for s in segments:
        s.setdefault("keep", True)
        s.setdefault("cut_reason", None)
    # 1. filler-only sentences
    if settings.get("cut_fillers", True):
        for s in segments:
            words = _real_words(s)
            if words and all(thai.is_filler(w["w"]) for w in words):
                s["keep"], s["cut_reason"] = False, "คำติดปาก (ไม่มีเนื้อหา)"
    # 2. false starts / repeated takes: keep the later, more complete take
    if settings.get("cut_repeats", True):
        live = [s for s in segments if s["keep"]]
        for i, a in enumerate(live):
            na = thai.normalize(a["text"])
            if len(na) < 4:
                continue
            for b in live[i + 1: i + 3]:
                nb = thai.normalize(b["text"])
                if b["start"] - a["end"] > 8:
                    break
                prefix = nb.startswith(na[: max(4, int(len(na) * 0.85))])
                ratio = difflib.SequenceMatcher(None, na, nb[: len(na) + 4]).ratio()
                if (prefix or ratio > 0.82) and len(na) <= len(nb) * 1.05:
                    a["keep"], a["cut_reason"] = False, f"พูดซ้ำ/เริ่มประโยคใหม่ — เก็บเทคที่สมบูรณ์กว่า ({b['id']})"
                    break
    # 3. near-empty blips with no content words (but never questions or numbers)
    for s in segments:
        if not s["keep"]:
            continue
        toks = [w["w"] for w in _real_words(s)]
        if (s["end"] - s["start"] < 0.35 and not thai.content_words(toks)
                and not any(thai.is_number(t) for t in toks)):
            s["keep"], s["cut_reason"] = False, "ช่วงสั้นที่ไม่มีข้อมูลสำคัญ"
    # 4. leading/trailing filler words inside sentences (only with real word-level timestamps)
    for s in segments:
        s["trim_start"], s["trim_end"] = s["start"], s["end"]
        if not (s["keep"] and s.get("word_level") and settings.get("cut_fillers", True)):
            continue
        words = _real_words(s)
        while len(words) > 1 and thai.is_filler(words[0]["w"]):
            words.pop(0)
        while len(words) > 1 and thai.is_filler(words[-1]["w"]):
            words.pop()
        if words:
            s["trim_start"], s["trim_end"] = words[0]["s"], words[-1]["e"]
    n_cut = sum(1 for s in segments if not s["keep"])
    log(f"วิเคราะห์การตัด: ตัด {n_cut} ประโยค จาก {len(segments)}")
    return segments


def build_clips(segments, silences, duration, settings, roles=None):
    """For each kept segment, compute source ranges (clips) to keep, shrinking long internal pauses."""
    pace = dict(PACING.get(settings.get("pacing", "normal"), PACING["normal"]))
    if settings.get("max_pause"):
        pace["max_pause"] = float(settings["max_pause"])
    kept = [s for s in segments if s["keep"]]
    last_b = 0.0
    for idx, s in enumerate(kept):
        prev_end = max(kept[idx - 1]["trim_end"] if idx else 0.0, last_b)
        next_start = kept[idx + 1]["trim_start"] if idx + 1 < len(kept) else duration
        a = max(prev_end, s["trim_start"] - pace["pre"], 0.0)
        # dramatic beats (hook question, turn, mystery) keep a bit more air after them
        role = (roles or {}).get(s["id"], s.get("role"))
        tail = pace["drama_pause"] if role in ("hook", "turn") or s["text"].rstrip().endswith("?") else pace["post"]
        b = min(next_start, s["trim_end"] + tail, duration)
        if b - a < 0.15:
            b = min(duration, a + 0.15)
        # split on long internal silences
        clips, cur = [], a
        for sa, sb in silences:
            if sb <= cur or sa >= b:
                continue
            sa, sb = max(sa, cur), min(sb, b)
            if sb - sa > pace["max_pause"] and sa > a + 0.05 and sb < b - 0.05:
                half = pace["keep_pause"] / 2
                clips.append([round(cur, 3), round(sa + half, 3)])
                cur = sb - half
        clips.append([round(cur, 3), round(b, 3)])
        s["clips"] = [c for c in clips if c[1] - c[0] > 0.08]
        if s["clips"]:
            last_b = s["clips"][-1][1]
    for s in segments:
        if not s["keep"]:
            s["clips"] = []
    return segments


def story_structure(segments):
    """Heuristic roles: hook, point, example, steps, turn, conclusion (+ flags for numbers/mystery/compare)."""
    kept = [s for s in segments if s["keep"]]
    if not kept:
        return {}
    roles = {}
    t0 = kept[0]["start"]
    for i, s in enumerate(kept):
        text = s["text"]
        role = "point"
        if thai.has_cue(text, "steps"):
            role = "steps"
        elif thai.starts_with_cue(text, "example") or thai.has_cue(text, "example") and len(text) < 60:
            role = "example"
        elif thai.starts_with_cue(text, "turn") or thai.has_cue(text, "turn") and "น่าแปลก" in text:
            role = "turn"
        if i >= len(kept) - 2 and thai.has_cue(text, "conclusion") or i == len(kept) - 1:
            role = "conclusion"
        if (s["start"] - t0 < 8 and i <= 1) or (i == 0):
            role = "hook"
        roles[s["id"]] = role
    return roles


def doc_frequency(segments):
    c = Counter()
    for s in segments:
        for w in s["words"]:
            if w["w"] != " ":
                c[w["w"]] += 1
    return c


def extract_numbers(seg):
    """[(token_index, number_text, unit, context_label)] from a segment's tokens."""
    toks = [w["w"] for w in seg["words"]]
    out = []
    for i, t in enumerate(toks):
        if re.fullmatch(r"\d[\d,\.]*%?", t.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))):
            unit = ""
            j = i + 1
            while j < len(toks) and toks[j] == " ":
                j += 1
            while j < len(toks) and toks[j] in thai.UNIT_WORDS and len(unit) < 12:   # e.g. ล้าน + บาท
                unit += toks[j]
                j += 1
            before = "".join(toks[max(0, i - 6): i]).strip()
            out.append((i, t, unit, before))
    return out


def extract_steps(seg):
    """Split a sentence spoken as a list ("ขั้นแรก ... ขั้นที่สอง ...") into (marker_word_index, text)."""
    toks = [w["w"] for w in seg["words"]]
    joined_positions = []
    for i in range(len(toks)):
        rest = "".join(toks[i:i + 4]).replace(" ", "")
        for m in thai.STEP_MARKERS:
            if rest.startswith(m.replace(" ", "")) and (not joined_positions or i > joined_positions[-1] + 1):
                joined_positions.append(i)
                break
    steps = []
    for k, i in enumerate(joined_positions):
        j = joined_positions[k + 1] if k + 1 < len(joined_positions) else len(toks)
        text = "".join(toks[i:j]).strip()
        steps.append({"word_index": i, "text": text})
    return steps if len(steps) >= 2 else []


def year_mentions(seg):
    out = []
    for i, w in enumerate(seg["words"]):
        t = w["w"].replace(",", "")
        if re.fullmatch(r"(1[5-9]\d\d|20\d\d|25\d\d)", t):
            out.append((i, t))
    return out
