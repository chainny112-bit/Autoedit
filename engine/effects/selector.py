"""Auto Effect Selection Engine (AI Director).

Per segment it scores importance, topic change, information complexity and speaking rate, then spends an
"effect budget" that depends on the density level, preferring effects the editing mode / detected genre weights
highly, avoiding repeats and over-stacking. Every decision carries a Thai reason so the user can audit it."""
import re
from collections import Counter

from .. import analyze as A, thai
from . import REGISTRY, capabilities
from .panels import PHONE_CUES, STORY_CUES, TECH_CUES, TIP_CUES

MODES = {
    "clean": {"name": "A — Clean Creator", "desc": "ภาพสะอาด ซับอ่านง่าย ตัดช่วงเงียบ Digital Zoom เล็กน้อย",
              "w": {"digital_zoom": 1.0, "glassy_type": 0.3, "checklist": 0.35, "chart_grow": 0.35}},
    "story": {"name": "B — Storytelling Cinematic", "desc": "เน้นเล่าเรื่อง ภาพประกอบ Pull-back Reveal และการเปลี่ยนฉาก",
              "w": {"pull_back": 1.0, "paper_cut": 1.0, "headline_wall": 0.7, "zoom_through": 0.9, "orbit": 0.6,
                    "vertigo": 0.5, "couch_wall": 0.6, "cover_story": 0.5, "digital_zoom": 0.6, "doodle_boil": 0.3,
                    "frame_break": 0.3, "phone_mockup": 0.3, "chart_grow": 0.5, "checklist": 0.4, "ui_world": 0.25,
                    "glassy_type": 0.4, "green_screen": 0.3}},
    "retention": {"name": "C — High-Retention Social", "desc": "จังหวะกระชับ Hook ชัด Punch-in ซับไดนามิก ภาพแทรก",
                  "w": {"digital_zoom": 1.0, "frame_break": 0.85, "headline_wall": 0.7, "checklist": 0.8,
                        "glassy_type": 0.6, "zoom_through": 0.7, "doodle_boil": 0.75, "chart_grow": 0.8,
                        "phone_mockup": 0.6, "pull_back": 0.5, "ui_world": 0.5, "cover_story": 0.5, "paper_cut": 0.3,
                        "orbit": 0.3, "vertigo": 0.3, "couch_wall": 0.3, "green_screen": 0.3}},
    "mograph": {"name": "D — Motion Graphics Heavy", "desc": "UI World, Headline Wall, Chart Grow, Glassy Type และกราฟิกเคลื่อนไหว",
                "w": {"ui_world": 1.0, "headline_wall": 1.0, "chart_grow": 1.0, "glassy_type": 1.0, "checklist": 0.9,
                      "phone_mockup": 0.8, "cover_story": 0.7, "doodle_boil": 0.5, "digital_zoom": 0.5,
                      "zoom_through": 0.6, "paper_cut": 0.4, "pull_back": 0.4, "frame_break": 0.3, "orbit": 0.2,
                      "vertigo": 0.2, "couch_wall": 0.3, "green_screen": 0.2}},
    "experimental": {"name": "E — Creative Experimental", "desc": "Frame Break, Orbit, Vertigo, Paper Cut, Zoom-through ตามความเหมาะสม",
                     "w": {"frame_break": 1.0, "orbit": 1.0, "vertigo": 0.9, "paper_cut": 1.0, "zoom_through": 1.0,
                           "doodle_boil": 0.8, "couch_wall": 0.8, "green_screen": 0.7, "cover_story": 0.7,
                           "pull_back": 0.7, "headline_wall": 0.5, "glassy_type": 0.5, "phone_mockup": 0.5,
                           "chart_grow": 0.6, "checklist": 0.5, "ui_world": 0.4, "digital_zoom": 0.5}},
    "auto": {"name": "F — Auto Director", "desc": "AI เลือกผสมเอฟเฟกต์จากเนื้อหา คำนึงถึงความเข้าใจง่ายและต้นทุนประมวลผล", "w": None},
}

GENRES = {
    "howto": {"name": "สอน / How-to", "cues": ["วิธี", "ขั้นตอน", "เคล็ดลับ", "ต้อง", "ควร", "อย่า", "ขั้นแรก", "ทำยังไง", "สอน", "ข้อควรระวัง"],
              "w": {"checklist": 1.0, "doodle_boil": 0.8, "digital_zoom": 0.9, "glassy_type": 0.5, "ui_world": 0.4,
                    "zoom_through": 0.4, "chart_grow": 0.6}},
    "story": {"name": "เล่าเรื่อง", "cues": STORY_CUES + ["ลึกลับ", "ปริศนา", "หายไป", "คืน", "เกิดขึ้น", "ปี"],
              "w": {"pull_back": 1.0, "paper_cut": 0.9, "headline_wall": 0.8, "vertigo": 0.5, "zoom_through": 0.6,
                    "couch_wall": 0.5, "orbit": 0.4, "digital_zoom": 0.6, "checklist": 0.5, "chart_grow": 0.6,
                    "cover_story": 0.45, "doodle_boil": 0.35, "frame_break": 0.4, "glassy_type": 0.4}},
    "review": {"name": "รีวิวสินค้า", "cues": ["รีวิว", "สินค้า", "ราคา", "ใช้งาน", "ลองใช้", "คุ้ม", "ข้อดี", "ข้อเสีย", "แบรนด์"],
               "w": {"phone_mockup": 1.0, "orbit": 0.8, "glassy_type": 0.9, "frame_break": 0.5, "digital_zoom": 0.7,
                     "cover_story": 0.6}},
    "news": {"name": "ข่าว / ข้อมูล", "cues": ["ข่าว", "รายงาน", "ข้อมูล", "สถิติ", "เปอร์เซ็นต์", "ยอด", "ล่าสุด", "ตัวเลข"],
             "w": {"ui_world": 1.0, "chart_grow": 1.0, "headline_wall": 0.9, "glassy_type": 0.6, "digital_zoom": 0.6,
                   "zoom_through": 0.5}},
    "promo": {"name": "โปรโมตธุรกิจ", "cues": ["บริการ", "ติดต่อ", "โปรโมชั่น", "ลูกค้า", "ธุรกิจ", "ร้าน", "บริษัท", "ทักมา", "สั่งซื้อ"],
              "w": {"cover_story": 1.0, "green_screen": 0.8, "pull_back": 0.8, "phone_mockup": 0.6, "glassy_type": 0.7,
                    "frame_break": 0.6}},
    "exciting": {"name": "ตื่นเต้น / ช็อก", "cues": ["ช็อก", "ไม่น่าเชื่อ", "ตกใจ", "ระทึก", "อันตราย", "สุดยอด", "!"],
                 "w": {"zoom_through": 1.0, "vertigo": 0.8, "frame_break": 0.7, "digital_zoom": 0.8, "headline_wall": 0.5}},
    "talking": {"name": "พูดหน้ากล้อง", "cues": [],
                "w": {"digital_zoom": 1.0, "frame_break": 0.7, "doodle_boil": 0.5, "glassy_type": 0.4,
                      "headline_wall": 0.4, "checklist": 0.5}},
}

DENSITY = {
    1: {"name": "MINIMAL", "min_imp": 0.75, "per_seg": 1, "gap": 12.0, "attention": 1.6, "transitions": 0.0,
        "heavy_seconds": 8, "desc": "เน้นภาพต้นฉบับ ซับ + ซูมเล็กน้อย กราฟิกเฉพาะจุดสำคัญ ไม่ใช้ Transition ที่ไม่จำเป็น"},
    2: {"name": "BALANCED", "min_imp": 0.45, "per_seg": 1, "gap": 6.0, "attention": 2.6, "transitions": 0.35,
        "heavy_seconds": 18, "desc": "ผสมผู้พูด ซับ ภาพแทรก และกราฟิกอย่างสมดุล (แนะนำ)"},
    3: {"name": "DYNAMIC", "min_imp": 0.25, "per_seg": 2, "gap": 3.0, "attention": 3.4, "transitions": 0.65,
        "heavy_seconds": 32, "desc": "เพิ่ม B-roll, Motion Graphics, Punch-in และ Animated Text อย่างมีจังหวะ"},
    4: {"name": "EXPERIMENTAL", "min_imp": 0.1, "per_seg": 3, "gap": 1.5, "attention": 4.6, "transitions": 0.9,
        "heavy_seconds": 60, "desc": "เอฟเฟกต์โดดเด่นและการเปลี่ยนฉากเชิงสร้างสรรค์ ผสมหลายแบบได้เมื่อเหมาะสม"},
}
ROLE_IMP = {"hook": 0.95, "turn": 0.75, "conclusion": 0.6, "steps": 0.7, "example": 0.5, "point": 0.4}
TOPIC_CUES = ["ต่อมา", "อีกเรื่อง", "ข้อต่อไป", "ถัดมา", "ส่วน", "นอกจากนี้", "แล้ว", "ต่อไป"]
EXCLAIM = ["ช็อก", "ไม่น่าเชื่อ", "ตกใจ", "น่ากลัว", "ระทึก", "!", "หายไป", "ไม่มีใคร"]


def detect_genre(segments):
    text = " ".join(s["text"] for s in segments if s.get("keep"))
    scores = {}
    for g, info in GENRES.items():
        hits = sum(text.count(c) for c in info["cues"])
        scores[g] = hits
    nums = sum(len(A.extract_numbers(s)) for s in segments if s.get("keep"))
    scores["news"] += nums * 0.7
    scores["talking"] = 1.5   # baseline: plain talking head
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    g1, g2 = ranked[0][0], ranked[1][0]
    reason = (f"ตรวจพบแนว '{GENRES[g1]['name']}' (คะแนน {ranked[0][1]:.1f})"
              + (f" รองลงมา '{GENRES[g2]['name']}'" if ranked[1][1] > 1 else ""))
    return {"genre": g1, "secondary": g2, "scores": {k: round(v, 1) for k, v in scores.items()}, "reason": reason}


def weights(mode, genre):
    if mode != "auto":
        return dict(MODES[mode]["w"])
    w = {k: 0.25 for k in REGISTRY}
    for k, v in GENRES[genre["genre"]]["w"].items():
        w[k] = max(w[k], v)
    for k, v in GENRES[genre["secondary"]]["w"].items():
        w[k] = max(w[k], v * 0.6)
    return w


def chart_series(seg):
    nums = A.extract_numbers(seg)
    toks = [w["w"] for w in seg["words"]]
    by_unit = {}
    for i, raw, unit, before in nums:
        clean = raw.replace(",", "").rstrip("%")
        if re.fullmatch(r"(1[5-9]\d\d|20\d\d|25\d\d)", clean):
            continue   # years are dates, not quantities
        try:
            v = float(clean)
        except ValueError:
            continue
        lab = _period_label(toks, i) or "".join(t for t in toks[max(0, i - 3):i] if t != " ").strip() \
            or f"ค่าที่ {len(by_unit.get(unit, [])) + 1}"
        by_unit.setdefault(unit or ("%" if raw.endswith("%") else ""), []).append(
            {"value": v, "raw": raw + (" " + unit if unit else ""), "unit": unit, "label": thai.short_title(lab, 12),
             "word_index": i})
    best = max(by_unit.values(), key=len) if by_unit else []
    return best if len(best) >= 2 else []


PERIOD_WORDS = ["ปีที่แล้ว", "ปีนี้", "ปีหน้า", "เดือนที่แล้ว", "เดือนนี้", "เดือนหน้า", "ไตรมาส", "เมื่อก่อน", "ตอนนี้",
                "ก่อนหน้า", "ล่าสุด", "สัปดาห์ที่แล้ว", "สัปดาห์นี้", "เมื่อวาน", "วันนี้", "ก่อน", "หลัง"]


def _period_label(toks, i):
    """The time period a number refers to, if it was said just before it ('ปีที่แล้ว ... 120 ล้าน')."""
    window = "".join(toks[max(0, i - 10):i])
    best, pos = None, -1
    for w in PERIOD_WORDS:
        p = window.rfind(w)
        if p > pos:
            best, pos = w, p
    return best


def checklist_items(seg):
    steps = A.extract_steps(seg)
    if steps:
        return steps
    if not any(c in seg["text"] for c in TIP_CUES):
        return []
    items, idx = [], 0
    for chunk in seg["text"].split(" "):
        n = len(thai.tokenize(chunk))
        if thai.visual_len(chunk) >= 4:
            items.append({"text": chunk.strip(), "word_index": _tok_index(seg, idx)})
        idx += n + 1
    # every item must itself be advice ("ต้อง/ควร/อย่า...") — a sentence that merely mentions tips isn't a list
    advice = [c for c in ("ต้อง", "ควร", "อย่า", "ห้าม") ]
    if not (2 <= len(items) <= 6 and all(thai.visual_len(i["text"]) <= 32 for i in items)
            and sum(any(c in i["text"] for c in advice) for i in items) >= max(2, len(items) - 1)):
        return []
    return items


def _tok_index(seg, approx):
    return min(approx, len(seg["words"]) - 1)


def features(plan, assets):
    kept = [s for s in plan["segments"] if s.get("keep") and s.get("clips")]
    df = A.doc_frequency(plan["segments"])
    out, prev_words = {}, None
    for k, s in enumerate(kept):
        toks = [w["w"] for w in s["words"]]
        cw = set(thai.content_words(toks))
        nums = A.extract_numbers(s)
        kw_idx = thai.pick_keywords(toks, df, 6)
        keywords = list(dict.fromkeys((s.get("highlight") or []) + [toks[i] for i in kw_idx if toks[i] != " "]))
        dur = sum(c[1] - c[0] for c in s["clips"])
        role = s.get("role") or "point"
        exclaim = any(c in s["text"] for c in EXCLAIM)
        imp = ROLE_IMP.get(role, 0.4) + 0.15 * min(2, len(nums)) + (0.1 if exclaim else 0) + \
            (0.05 if s.get("highlight") else 0)
        overlap = len(cw & prev_words) / max(1, len(cw | prev_words)) if prev_words is not None else 1
        topic_change = prev_words is not None and (overlap < 0.12 and (
            role in ("turn", "steps", "conclusion") or any(s["text"].startswith(c) for c in TOPIC_CUES)))
        b = s.get("broll") or {}
        out[s["id"]] = {
            "id": s["id"], "role": role, "text": s["text"], "dur": dur, "importance": round(min(1.0, imp), 2),
            "numbers": nums, "chart_series": chart_series(s), "checklist": checklist_items(s), "keywords": keywords,
            "highlight": s.get("highlight") or [], "mystery": thai.has_cue(s["text"], "mystery"), "exclaim": exclaim,
            "topic_change": topic_change, "speech_rate": round(len(s["text"].replace(" ", "")) / max(0.5, dur), 1),
            "has_asset": b.get("kind") == "asset" or bool(s.get("_fx_asset")), "face": any(s.get("faces") or []),
            "layout_base": s.get("layout", "full"), "is_first": k == 0, "is_last": k == len(kept) - 1,
            "title": s.get("title", ""), "t": round(s["start"], 2),
        }
        prev_words = cw
    return out


def direct(plan, settings, assets=(), caps=None, log=print):
    """Choose effects + transitions for every kept segment. Mutates plan; returns the direction summary."""
    caps = caps or capabilities()
    mode = settings.get("mode", "auto")
    mode = mode if mode in MODES else "auto"
    level = int(settings.get("density", 2))
    level = level if level in DENSITY else 2
    D = DENSITY[level]
    intensity = settings.get("intensity", "medium")
    allowed = set(settings.get("allowed_effects") or [])
    banned = set(settings.get("banned_effects") or [])
    trans_allowed = set(settings.get("transitions") or ["cut", "flash", "zoom_through"])
    avoid = set(settings.get("_avoid") or [])
    genre = detect_genre(plan["segments"])
    W = weights(mode, genre)
    chroma = settings.get("_chroma") or {}
    ctx = {"caps": {**caps, "chroma": bool(chroma.get("share", 0) > 0.35)}, "mode": mode, "genre": genre["genre"],
           "density": level, "intensity": intensity}
    feats = features(plan, assets)
    usage, last_major_t, heavy_used = Counter(), -99.0, 0.0
    recent = []          # effect ids of the previous segments
    last_zoom_through = -99
    kept = [s for s in plan["segments"] if s.get("keep") and s.get("clips")]
    max_uses = max(1, -(-len(kept) // (4 if level < 4 else 3)))   # no single effect dominates the video

    basic_min = {1: 0.68, 2: 0.0, 3: 0.0, 4: 0.0}[level] + (0.2 if mode == "clean" else 0)
    for k, s in enumerate(kept):
        f = feats[s["id"]]
        s["effects"], s["transition_in"] = [], {"id": "cut", "reason": "ตัดตรง (ค่าเริ่มต้น)"}
        imp = f["importance"]
        b0 = (s.get("broll") or {}).get("kind", "none")
        if b0 not in ("none", "asset") and imp < basic_min:
            # basic info graphics are motion graphics too: they obey the density budget
            s["broll_suppressed"] = s.get("broll")
            s["broll"] = {"kind": "none"}
            if s.get("layout") in ("pip", "split", "broll_full"):
                s["layout"] = "full"
            f["layout_base"] = "full"
        budget = D["attention"] * (0.55 + 0.6 * imp)
        used = (1.0 if s.get("title") else 0) + (1.2 if s.get("layout") in ("pip", "split") else 0)
        cands = []
        for eid, eff in REGISTRY.items():
            if eff.category == "transition" or eid in banned or (allowed and eid not in allowed):
                continue
            w = W.get(eid, 0)
            if w <= 0:
                continue
            ok, _ = eff.available(ctx["caps"])
            if not ok:
                continue
            r = eff.eligible(f, ctx)
            if not r:
                continue
            score, reason, override = (r + ({},))[:3] if len(r) == 2 else r
            score *= w * (0.5 + imp)
            if eid in recent[-2:]:
                score *= 0.25                       # variety: no back-to-back repeats without reason
            score *= 0.75 ** usage[eid]
            if eid in avoid:
                score *= 0.45                       # creative variant: prefer what the other versions didn't use
            cands.append((score, eid, reason, override))
        cands.sort(reverse=True)
        chosen_cats, layout = set(), s.get("layout", "full")
        for score, eid, reason, override in cands:
            eff = REGISTRY[eid]
            if len(s["effects"]) >= D["per_seg"] or score < 0.12:
                break
            cat = "visual" if eff.category in ("camera", "composite") else eff.category
            if cat in chosen_cats and not (level == 4 and cat == "overlay"):
                continue
            major = eff.attention >= 1.4
            if imp < D["min_imp"] and major:
                continue
            if major and s["start"] - last_major_t < D["gap"] and imp < 0.9:
                continue
            cost = eff.attention - (1.2 if eff.category == "panel" and layout in ("pip", "split") else 0)
            if used + cost > budget:
                continue
            if eff.layout == "full" and layout not in ("full",) and eff.category != "panel":
                continue
            if eff.category == "panel":
                if layout not in ("pip", "full") or f["role"] == "hook" and layout == "full":
                    continue    # the hook keeps the presenter on screen
                if any(REGISTRY[e["id"]].layout == "full" for e in s["effects"]):
                    continue    # a full-frame effect is already chosen: don't split the screen under it
            if usage[eid] >= max_uses:
                continue
            if eff.category == "composite" or eid == "vertigo":
                secs = f["dur"]
                if heavy_used + secs > D["heavy_seconds"]:
                    continue
                heavy_used += secs
            if eff.category == "panel":
                layout = "pip"
            s["effects"].append({"id": eid, "params": eff.clean_params(override, intensity), "reason": reason,
                                 "score": round(score, 2), "auto": True})
            chosen_cats.add(cat)
            used += cost
            usage[eid] += 1
            if major:
                last_major_t = s["start"]
        # layout consequences
        if layout != s.get("layout"):
            s["layout"] = layout
            if (s.get("broll") or {}).get("kind") == "none":
                s["broll"] = {"kind": "keyword", "text": (s.get("highlight") or [""])[0]}
        if any(REGISTRY[e["id"]].category in ("camera", "composite") for e in s["effects"]):
            s["zoom"] = "none"      # don't stack static punch-in on top of a camera effect
        if any(e["id"] in ("glassy_type", "cover_story") for e in s["effects"]):
            s["title_style"] = "effect"   # the effect presents the title instead of a title card
        # transition into this segment
        if k > 0 and D["transitions"] > 0:
            zt = REGISTRY["zoom_through"]
            r = zt.eligible(f, ctx) if "zoom_through" in trans_allowed and "zoom_through" not in banned and \
                (not allowed or "zoom_through" in allowed) else None
            prev_dur = kept[k - 1]["clips"][-1][1] - kept[k - 1]["clips"][-1][0]
            if r and r[0] * D["transitions"] >= 0.2 and k - last_zoom_through >= 3 and prev_dur > 0.8 and \
                    s["clips"][0][1] - s["clips"][0][0] > 0.8 and used + zt.attention <= budget + 0.5:
                s["transition_in"] = {"id": "zoom_through", "params": zt.clean_params({}, intensity), "reason": r[1]}
                last_zoom_through = k
            elif "flash" in trans_allowed and f["role"] == "turn" and D["transitions"] >= 0.35:
                s["transition_in"] = {"id": "flash", "reason": "จุดหักมุม → แฟลชสั้นสีแบรนด์"}
        # sound design follows the visual decision, not the other way round
        if settings.get("sfx", True):
            if s["transition_in"]["id"] in ("zoom_through", "flash"):
                s["sfx"] = "whoosh"
            elif any(e["id"] in ("frame_break", "cover_story", "pull_back") for e in s["effects"]) and s.get("sfx") == "none":
                s["sfx"] = "hit"
        s["effect_budget"] = {"importance": imp, "budget": round(budget, 2), "used": round(used, 2)}
        recent += [e["id"] for e in s["effects"]] or ["-"]

    counts = Counter(e["id"] for s in kept for e in s["effects"])
    trans = Counter(s["transition_in"]["id"] for s in kept)
    top = ", ".join(f"{REGISTRY[e].name} ×{n}" for e, n in counts.most_common(4)) or "ไม่มี (ซับ + การตัดเท่านั้น)"
    summary = (f"{MODES[mode]['name']} · ความหนาแน่น {D['name']} · ความเข้ม {intensity.upper()} · {genre['reason']}. "
               f"เอฟเฟกต์หลัก: {top}. Transition: " + ", ".join(f"{k} ×{v}" for k, v in trans.items()))
    direction = {"mode": mode, "mode_name": MODES[mode]["name"], "density": level, "density_name": D["name"],
                 "intensity": intensity, "genre": genre, "counts": dict(counts), "transitions": dict(trans),
                 "summary": summary, "heavy_seconds": round(heavy_used, 1)}
    plan["direction"] = direction
    log("AI Director: " + summary)
    return direction
