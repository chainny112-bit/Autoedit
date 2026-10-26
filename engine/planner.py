"""Turns analysis into an editable Editing Plan (one row per spoken sentence)."""
import re

from . import analyze as A
from . import thai, vision

DEFAULT_SETTINGS = {
    "fps": "source",            # or a number, e.g. 30
    "accent": "#BC0000",        # brand red (Red Rabbit)
    "accent2": "#A8CE20",       # brand lime (accent dot)
    "subtitle_mode": "keyword",  # keyword | karaoke
    "subtitle_size": 92,
    "subtitle_max_chars": 15,
    "pacing": "normal",         # calm | normal | fast
    "zoom_intensity": 1.15,
    "broll_density": "normal",  # low | normal | high
    "title_cards": True,
    "music": "generated",       # generated | upload | none
    "music_db": -26,
    "sfx": True,
    "denoise": True,
    "cut_fillers": True,
    "cut_repeats": True,
    "asr_model": "small",
    "language": "th",
    "use_llm": "off",           # on = user allowed paid Claude API calls; off = never call
    "allow_ai_images": False,   # user consent for AUTOEDIT_IMAGE_CMD (may cost money)
    "mode": "auto",             # clean | story | retention | mograph | experimental | auto
    "density": 2,               # 1 minimal | 2 balanced | 3 dynamic | 4 experimental
    "intensity": "medium",      # low | medium | high
    "subtitle_font": "Kanit ExtraBold",
    "allowed_effects": [],
    "banned_effects": [],
    "transitions": ["cut", "flash", "zoom_through"],
    "export_profile": "1080p_high",
    "aspect": "9:16",
    "brand_name": "RED RABBIT",
    "preset_id": "redrabbit_signature",
    "review_before_export": False,
    "use_reference_colors": True,
    "ai_label": True,
}

LAYOUTS = ["full", "pip", "split", "broll_full", "fit"]
ZOOMS = ["none", "punch", "close"]
BROLL_KINDS = ["none", "stat", "steps", "timeline", "keyword", "compare", "placeholder", "asset"]
SFX = ["none", "whoosh", "pop", "hit"]
PANEL_EFFECTS = {"ui_world", "chart_grow", "checklist", "phone_mockup", "paper_cut"}
DENSITY_GAP = {"low": 2, "normal": 1, "high": 0}  # min plain segments between decorative b-rolls


def make_subs(seg, settings):
    """Readable one-line subtitle phrases with timings and highlighted words."""
    words = seg["words"]
    toks = [w["w"] for w in words]
    # highlights may be multi-word phrases: mark every token overlapping an occurrence in the sentence
    joined = "".join(toks)
    starts = [0]
    for t in toks:
        starts.append(starts[-1] + len(t))
    hl_idx = set()
    for h in seg.get("highlight") or []:
        h = h.strip()
        pos = joined.find(h) if h else -1
        while pos >= 0:
            hl_idx.update(i for i in range(len(toks)) if starts[i] < pos + len(h) and starts[i + 1] > pos and toks[i] != " ")
            pos = joined.find(h, pos + len(h))
    out = []
    for a, b in thai.chunk_phrases(toks, int(settings.get("subtitle_max_chars", 16))):
        timed = [w for w in words[a:b] if w["s"] is not None]
        if not timed:
            continue
        parts = [{"w": w["w"], "s": w["s"], "e": w["e"], "hl": i in hl_idx} for i, w in enumerate(words[a:b], a)]
        out.append({"text": "".join(toks[a:b]), "s": timed[0]["s"], "e": timed[-1]["e"], "parts": parts})
    # make every phrase last until the next one (min 0.5 s) so text doesn't flicker
    for i, p in enumerate(out):
        nxt = out[i + 1]["s"] if i + 1 < len(out) else p["e"] + 0.25
        p["e"] = max(p["e"], min(nxt, p["s"] + 0.5))
        if i + 1 < len(out):
            p["e"] = min(max(p["e"], nxt), nxt)
    return out


def _match_asset(seg, assets):
    toks = set(thai.content_words([w["w"] for w in seg["words"]]))
    text = seg["text"]
    best, score = None, 0
    for a in assets:
        if a.get("role") != "broll":
            continue
        sc = 0
        for tag in a.get("tags", []):
            if len(tag) >= 2 and (tag in text or any(tag in t or t in tag for t in toks if len(t) >= 3)):
                sc += thai.visual_len(tag)
        if sc > score:
            best, score = a, sc
    return best


def build_plan(source, segments, vis, settings, assets=(), llm=None, log=print):
    st = {**DEFAULT_SETTINGS, **(settings or {})}
    roles = A.story_structure(segments)
    llm = llm or {}
    for sid, r in llm.items():
        if sid in roles and r.get("role"):
            roles[sid] = r["role"]
    A.build_clips(segments, vis_silences(source), source["duration"], st, roles)
    df = A.doc_frequency(segments)
    landscape = source["width"] > source["height"] * 1.05
    gap_needed = DENSITY_GAP.get(st["broll_density"], 1)

    plan_segs, since_broll, zoom_flip, turn_flip, titles_at = [], 99, False, True, []
    used_assets = set()
    for seg in segments:
        sid = seg["id"]
        role = roles.get(sid)
        L = llm.get(sid, {})
        row = {
            "id": sid, "start": seg["start"], "end": seg["end"], "text": seg["text"], "words": seg["words"],
            "word_level": seg.get("word_level", False), "keep": seg["keep"], "cut_reason": seg["cut_reason"],
            "role": role, "clips": seg.get("clips", []), "layout": "full", "zoom": "none",
            "broll": {"kind": "none"}, "title": "", "sfx": "none", "notes": [],
            "spelling": thai.unknown_words(seg["text"]),
        }
        # faces per clip (for reframing and keeping graphics off the face)
        row["faces"] = [vision.face_in_range(vis, c[0], c[1]) for c in row["clips"]]
        if not seg["keep"]:
            row["highlight"] = []
            plan_segs.append(row)
            continue

        toks = [w["w"] for w in seg["words"]]
        if L.get("keywords"):
            row["highlight"] = [k for k in L["keywords"] if k in toks][:2] or [toks[i] for i in thai.pick_keywords(toks, df, 1)]
        else:
            n_hl = 2 if len(seg["text"]) > 45 else 1
            row["highlight"] = [toks[i] for i in thai.pick_keywords(toks, df, n_hl)]

        nums = A.extract_numbers(seg)
        steps = A.extract_steps(seg) if role == "steps" or thai.has_cue(seg["text"], "steps") else []
        years = A.year_mentions(seg)
        asset = _match_asset(seg, [a for a in assets if a["name"] not in used_assets])
        mystery = thai.has_cue(seg["text"], "mystery")
        decorative_ok = since_broll >= gap_needed and role not in ("hook", "conclusion")
        lk = L.get("broll")

        b = {"kind": "none"}
        if steps:
            b = {"kind": "steps", "items": [x["text"] for x in steps], "word_index": [x["word_index"] for x in steps],
                 "label": "ขั้นตอน"}
        elif years and (lk in (None, "timeline") or not nums or len(nums) == len(years)):
            i, y = years[0]
            context = "".join(t for t in toks[max(0, i - 6):i]).strip()
            b = {"kind": "timeline", "year": y, "caption": thai.short_title("".join(toks[i + 1:]), 18) or context,
                 "word_index": i}
        elif nums and lk in (None, "stat"):
            i, n, unit, before = nums[0]
            b = {"kind": "stat", "value": n, "unit": unit, "caption": thai.short_title(before, 18) if before else "",
                 "word_index": i, "source_note": "ตัวเลขจากคำพูดในคลิป"}
        elif asset and (decorative_ok or lk not in (None, "none")):
            b = {"kind": "asset", "asset": asset["name"], "source": asset.get("source", "user"),
                 "label": {"ai": "ภาพสร้างด้วย AI", "stock": "ภาพประกอบ (Stock)"}.get(asset.get("source"), "ภาพประกอบ")}
            used_assets.add(asset["name"])
        elif (lk in ("atmosphere", "illustration") or (lk is None and mystery)) and decorative_ok:
            desc = L.get("broll_description") or _placeholder_desc(seg["text"])
            b = {"kind": "placeholder", "description": desc,
                 "prompt": L.get("image_prompt") or _placeholder_prompt(seg["text"]),
                 "label": "ภาพจำลอง / ภาพประกอบ"}
        elif lk == "keyword" and decorative_ok and row["highlight"]:
            b = {"kind": "keyword", "text": row["highlight"][0]}
        elif (lk == "compare" or thai.has_cue(seg["text"], "compare") and " " in seg["text"]) and decorative_ok:
            left, right = _split_compare(seg["text"])
            if left and right:
                b = {"kind": "compare", "left": left, "right": right}
        row["broll"] = b

        if b["kind"] == "none":
            row["layout"] = "fit" if (landscape and not any(row["faces"])) else "full"
            since_broll += 1
        elif b["kind"] == "compare":
            row["layout"] = "split"
            since_broll = 0
        else:
            row["layout"] = "pip"
            since_broll = 0

        # zoom: alternate on full-frame shots to give jump cuts rhythm; close-up on turns
        if row["layout"] in ("full",):
            if role == "turn":
                row["zoom"] = "close" if turn_flip else "punch"
                turn_flip = not turn_flip
            elif role == "conclusion":
                row["zoom"] = "none"
            else:
                row["zoom"] = "punch" if zoom_flip else "none"
                zoom_flip = not zoom_flip

        # title cards: hook + big turns, at most one per ~20 s
        tc = (L.get("title_card") or "").strip()
        if st["title_cards"] and row["layout"] in ("full", "fit"):
            if role == "hook" and not titles_at:
                row["title"] = tc or thai.key_clause(seg["text"], row["highlight"], 20)
            elif tc and role == "turn" and (not titles_at or seg["start"] - titles_at[-1] > 20):
                row["title"] = tc
            if row["title"]:
                titles_at.append(seg["start"])

        # sound design: only on structural moments
        if st["sfx"]:
            if row["title"]:
                row["sfx"] = "hit"
            elif row["layout"] in ("pip", "split") and b["kind"] in ("stat", "timeline"):
                row["sfx"] = "pop"
            elif role == "turn" or b["kind"] in ("placeholder", "asset", "steps"):
                row["sfx"] = "whoosh"
        if row["spelling"]:
            row["notes"].append("ตรวจคำ: " + ", ".join(row["spelling"]))
        plan_segs.append(row)

    _limit_sfx(plan_segs)
    for row in plan_segs:
        row["subs"] = make_subs(row, st) if row["keep"] else []
    out_dur = sum(c[1] - c[0] for r in plan_segs for c in r["clips"])
    log(f"สร้าง Editing Plan: {sum(r['keep'] for r in plan_segs)} ประโยค, ความยาวใหม่ ~{out_dur:.1f}s "
        f"(เดิม {source['duration']:.1f}s)")
    return {"version": 1, "settings": st, "source": source, "segments": plan_segs,
            "estimated_duration": round(out_dur, 2)}


def _limit_sfx(rows):
    last = -99
    for r in rows:
        if r.get("sfx", "none") != "none" and r["keep"]:
            if r["start"] - last < 4:
                r["sfx"] = "none"
            else:
                last = r["start"]


def _placeholder_desc(text):
    t = text
    if "ทะเลสาบ" in t:
        return "ภาพบรรยากาศทะเลสาบยามค่ำคืน มีหมอก แสงจันทร์"
    if "บ้าน" in t or "หมู่บ้าน" in t:
        return "ภาพบรรยากาศหมู่บ้านร้างเงียบสงัด แสงสลัวโทนแดง"
    if "ป่า" in t:
        return "ภาพป่าทึบยามค่ำคืน แสงลอดผ่านต้นไม้"
    return "ภาพบรรยากาศลึกลับ โทนมืด แสงสีแดงเข้ม สอดคล้องกับ: " + thai.short_title(text, 24)


def _placeholder_prompt(text):
    base = "cinematic illustration, dark moody atmosphere, deep red rim light, film grain, vertical composition"
    if "ทะเลสาบ" in text:
        return "misty remote lake at night, abandoned wooden cabins, " + base
    if "บ้าน" in text:
        return "abandoned village at night, a lantern glowing in an empty doorway, " + base
    return "mysterious empty landscape at dusk, " + base


def _split_compare(text):
    for sep in ["ในขณะที่", "เทียบกับ", "ต่างจาก", " vs ", " แต่"]:
        if sep in text:
            l, r = text.split(sep, 1)
            return thai.short_title(l, 18), thai.short_title(sep.strip() + r, 18)
    return None, None


def vis_silences(source):
    return source.get("_silences", [])


def apply_edits(old_plan, new_plan, speech_mask=None):
    """Merge a user-edited plan: re-time words if text changed, recompute clips if keep changed."""
    from . import transcribe as T
    old = {s["id"]: s for s in old_plan["segments"]}
    st = {**DEFAULT_SETTINGS, **new_plan.get("settings", old_plan["settings"])}
    for row in new_plan["segments"]:
        o = old.get(row["id"])
        if not o:
            continue
        row["words"] = o["words"]
        row["start"], row["end"] = o["start"], o["end"]
        if row.get("text", o["text"]).strip() != o["text"].strip():
            rt = T.retime_text(o, row["text"].strip(), speech_mask)
            row["words"] = rt["words"]
            row["word_level"] = False
            row["spelling"] = thai.unknown_words(row["text"])
        for k in ("layout", "zoom", "sfx"):
            allowed = {"layout": LAYOUTS, "zoom": ZOOMS, "sfx": SFX}[k]
            if row.get(k) not in allowed:
                row[k] = o.get(k, allowed[0])
        if (row.get("broll") or {}).get("kind") not in BROLL_KINDS:
            row["broll"] = {"kind": "none"}
        panel_fx = any(e.get("id") in PANEL_EFFECTS for e in row.get("effects") or [])
        if row["broll"]["kind"] == "none" and row["layout"] in ("pip", "split", "broll_full") and not panel_fx:
            row["layout"] = "full"
        if panel_fx and row["layout"] in ("full", "fit"):
            row["layout"] = "pip"     # a panel effect needs a panel to draw into
        if row["broll"]["kind"] != "none" and row["layout"] in ("full", "fit"):
            row["layout"] = "pip"
        row.setdefault("faces", o.get("faces", []))
        row["highlight"] = [h for h in (row.get("highlight") or []) if isinstance(h, str)]
        row["subs"] = make_subs(row, st) if row.get("keep") else []
    new_plan["settings"] = st
    new_plan["source"] = old_plan["source"]
    return new_plan
