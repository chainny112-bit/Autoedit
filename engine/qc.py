"""Pre-delivery checks on the rendered file and the plan that produced it."""
import re
import subprocess

from . import graphics as G, media, thai


def _issue(level, code, msg, fix=None, at=None):
    return {"level": level, "code": code, "message": msg, "fix": fix, "at": at}


def check(result, plan, preview=False):
    issues, info = [], {}
    path = result["path"]
    # 1. file plays: streams + full decode
    try:
        pr = media.probe(path)
        info["probe"] = pr
    except Exception as e:
        return [_issue("error", "unplayable", f"เปิดไฟล์ไม่ได้: {e}")], info
    exp_w, exp_h = result["size"]
    if (pr["width"], pr["height"]) != (exp_w, exp_h):
        issues.append(_issue("error", "resolution", f"ความละเอียด {pr['width']}x{pr['height']} ไม่ตรงกับ {exp_w}x{exp_h}"))
    if pr["vcodec"] != "h264" or pr["acodec"] != "aac":
        issues.append(_issue("error", "codec", f"codec {pr['vcodec']}/{pr['acodec']} (ต้องเป็น h264/aac)"))
    if abs(pr["duration"] - result["duration"]) > 0.25:
        issues.append(_issue("warn", "duration", f"ความยาวไฟล์ {pr['duration']:.2f}s ต่างจากแผน {result['duration']:.2f}s"))
    dec = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-f", "null", "-"],
                         capture_output=True, text=True)
    err_lines = [l for l in dec.stderr.splitlines() if l.strip()]
    if dec.returncode != 0 or err_lines:
        issues.append(_issue("error", "decode", "พบข้อผิดพลาดตอนถอดรหัสวิดีโอ: " + " | ".join(err_lines[:3])))
    full = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vf", "blackdetect=d=0.25:pix_th=0.06",
                           "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    blacks = re.findall(r"black_start:([\d\.]+) black_end:([\d\.]+)", full)
    for a, b in blacks:
        issues.append(_issue("error", "black", f"เฟรมดำ {float(a):.2f}–{float(b):.2f}s", at=float(a)))
    m = re.search(r"max_volume: (-?[\d\.]+) dB", full)
    mean = re.search(r"mean_volume: (-?[\d\.]+) dB", full)
    if m:
        info["max_volume_db"] = float(m.group(1))
        if float(m.group(1)) > -0.3:
            issues.append(_issue("error", "clipping", f"เสียงพีค {m.group(1)} dB เสี่ยงเสียงแตก", fix="lower_gain"))
    if mean:
        info["mean_volume_db"] = float(mean.group(1))
        if float(mean.group(1)) < -35:
            issues.append(_issue("warn", "quiet", f"ระดับเสียงเฉลี่ยต่ำ ({mean.group(1)} dB)"))

    # 2. subtitles vs speech timing, readability
    for seg in plan["segments"]:
        if not seg.get("keep"):
            continue
        for p in seg.get("subs", []):
            if p["e"] - p["s"] < 0.35:
                issues.append(_issue("warn", "sub_short", f"ซับ '{p['text']}' แสดงสั้นเกินไป ({p['e'] - p['s']:.2f}s)",
                                     at=p["s"]))
            if not (seg["start"] - 0.3 <= p["s"] <= seg["end"] + 0.3):
                issues.append(_issue("error", "sub_sync", f"ซับ '{p['text']}' อยู่นอกช่วงเสียงพูด", at=p["s"]))
        if seg.get("spelling"):
            issues.append(_issue("warn", "spelling", f"{seg['id']}: คำที่ควรตรวจการสะกด → {', '.join(seg['spelling'])}",
                                 at=seg["start"]))
        if not seg.get("word_level") and seg.get("subs"):
            pass

    # 3. speech cut mid-word: clip edges must not land inside words
    for seg in plan["segments"]:
        if not seg.get("keep"):
            continue
        words = [w for w in seg["words"] if w["s"] is not None]
        for a, b in seg.get("clips", []):
            for w in words:
                inside_a = w["s"] + 0.03 < a < w["e"] - 0.03
                inside_b = w["s"] + 0.03 < b < w["e"] - 0.03
                if (inside_a or inside_b) and seg.get("word_level"):
                    issues.append(_issue("error", "word_cut", f"จุดตัด {a if inside_a else b:.2f}s อยู่กลางคำ '{w['w']}'",
                                         fix="extend_clip", at=a))
            if words and (a > words[0]["s"] + 0.02 and a == seg["clips"][0][0]):
                issues.append(_issue("error", "head_cut", f"{seg['id']}: ตัดพยางค์ต้นประโยค", fix="extend_clip"))
            if words and (b < words[-1]["e"] - 0.02 and b == seg["clips"][-1][1]):
                issues.append(_issue("error", "tail_cut", f"{seg['id']}: ตัดพยางค์ท้ายประโยค", fix="extend_clip"))

    # 4. layout: graphics over the face, overflow outside frame
    faces = [(it["out"], it["out"] + it["d"], it["face_out"]) for it in result["items"] if it.get("face_out")]
    for (t0, t1, x0, y0, x1, y1, kind) in result["boxes"]:
        if x0 < -2 or x1 > G.W + 2 or y0 < -2 or y1 > G.H + 2:
            issues.append(_issue("error", "overflow", f"{kind} ล้นเฟรม ที่ {t0:.2f}s", at=t0))
        if kind == "sub" and (x0 < G.SAFE["left"] - 30 or x1 > G.SAFE["right"] + 30 or y1 > G.SAFE["bottom"] + 40):
            issues.append(_issue("warn", "safe_zone", f"ซับออกนอก Safe Zone ที่ {t0:.2f}s", at=t0))
        for (f0, f1, fb) in faces:
            if f1 <= t0 + 0.05 or f0 >= t1 - 0.05:  # touching at a cut is not an overlap
                continue
            ox = min(x1, fb[2]) - max(x0, fb[0])
            oy = min(y1, fb[3]) - max(y0, fb[1])
            if ox > 0 and oy > 0 and ox * oy > 0.15 * (fb[2] - fb[0]) * (fb[3] - fb[1]):
                issues.append(_issue("warn", "face_overlap", f"{kind} ทับใบหน้าผู้พูดที่ {max(t0, f0):.2f}s",
                                     at=max(t0, f0)))
                break
    # 5. effects: fallbacks, mask integrity, data fidelity, transitions
    for r in result.get("effects_report") or []:
        if r["status"] == "failed":
            issues.append(_issue("error", "effect_failed", f"{r['seg']}: เอฟเฟกต์ {r['effect']} ผิดพลาด — {r['msg']}",
                                 fix="drop_effect", at=None))
            issues[-1]["effect"], issues[-1]["seg"] = r["effect"], r["seg"]
        elif r["status"] == "skipped":
            issues.append(_issue("warn", "effect_skipped", f"{r['seg']}: {r['effect']} ไม่ถูกแสดง — {r['msg']}"))
        elif r["status"] == "fallback":
            issues.append(_issue("info", "effect_fallback", f"{r['seg']}: {r['effect']} ใช้ Fallback — {r['msg']}"))
        if r.get("mask") and not r["mask"].get("ok", True):
            issues.append(_issue("info", "mask_quality", f"{r['seg']}: mask ไม่ผ่านเกณฑ์ ({r['mask'].get('reason')}) "
                                                         "→ ใช้รูปแบบที่ไม่ต้องตัดขอบแทน"))
    for seg in plan["segments"]:
        for e in seg.get("effects") or []:
            if e["id"] in ("chart_grow", "ui_world"):
                from .effects.selector import chart_series
                for sv in chart_series(seg):
                    if sv["raw"].split(" ")[0] not in seg["text"]:
                        issues.append(_issue("error", "data_mismatch",
                                             f"{seg['id']}: ค่าในกราฟ {sv['raw']} ไม่พบในบทพูด"))
    fps = result.get("fps") or 30
    for it in result.get("items") or []:
        if it.get("trans_in") is not None:
            t = it["out"]
            for a, b in blacks:
                if float(a) - 0.2 <= t <= float(b) + 0.2:
                    issues.append(_issue("error", "transition_black", f"ภาพดำที่จุดเปลี่ยนฉาก {t:.2f}s", at=t))
    for (t0, t1, x0, y0, x1, y1, kind) in result.get("boxes") or []:
        if kind == "sub" and (y1 - y0) / 1.5 < 34:
            issues.append(_issue("warn", "readability", f"ซับขนาดเล็กเกินไปที่ {t0:.2f}s", at=t0))
            break

    # 6. smoothness, audio quality, delivery compatibility
    extra = stream_checks(path, result)
    issues += extra

    # 7. placeholders still in the edit
    ph = [s["id"] for s in plan["segments"] if s.get("keep") and (s.get("broll") or {}).get("kind") == "placeholder"]
    if ph:
        issues.append(_issue("info", "placeholder", f"ยังมี Placeholder ภาพประกอบ {len(ph)} จุด ({', '.join(ph)}) "
                                                    "— อัปโหลดภาพ/สร้างภาพ AI แล้วเลือกในแผนเพื่อแทนที่"))
    # de-duplicate
    seen, out = set(), []
    for i in issues:
        k = (i["code"], i["message"])
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out, info


def stream_checks(path, result):
    import json as _json
    out = []
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets,r_frame_rate,avg_frame_rate,profile,pix_fmt,level", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        v = _json.loads(p.stdout)["streams"][0]
    except Exception:
        return [_issue("error", "probe", "อ่านข้อมูลสตรีมวิดีโอไม่ได้")]
    exp = round(result["duration"] * result["fps"])
    got = int(v.get("nb_read_packets") or 0)
    if abs(got - exp) > 2:
        out.append(_issue("warn", "frames", f"จำนวนเฟรม {got} ต่างจากที่คาด {exp} (อาจกระตุก)"))
    if v.get("r_frame_rate") != v.get("avg_frame_rate"):
        out.append(_issue("warn", "vfr", f"เฟรมเรตไม่คงที่ ({v.get('r_frame_rate')} vs {v.get('avg_frame_rate')})"))
    if v.get("pix_fmt") != "yuv420p" or (v.get("profile") or "") not in ("High", "Main", "Constrained Baseline"):
        out.append(_issue("error", "compat", f"รูปแบบวิดีโอ {v.get('profile')}/{v.get('pix_fmt')} อาจเล่นบนมือถือไม่ได้"))
    if int(v.get("level") or 0) > 42:
        out.append(_issue("warn", "level", f"H.264 level {v.get('level')} สูงกว่า 4.2"))
    with open(path, "rb") as f:   # faststart: 'moov' must come before 'mdat' for instant playback on upload
        head = f.read(64 * 1024)
    mo, md = head.find(b"moov"), head.find(b"mdat")
    if mo < 0 or (0 <= md < mo):
        out.append(_issue("warn", "faststart", "ไฟล์ไม่ได้จัด moov ไว้ต้นไฟล์ (เล่นออนไลน์ช้า)"))
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=sample_rate,channels,codec_name,profile", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        aa = _json.loads(a.stdout)["streams"][0]
        if int(aa["sample_rate"]) != 48000 or int(aa["channels"]) != 2:
            out.append(_issue("warn", "audio_fmt", f"เสียง {aa['sample_rate']}Hz/{aa['channels']}ch (คาด 48kHz สเตอริโอ)"))
    except Exception:
        out.append(_issue("error", "no_audio", "ไม่มีสตรีมเสียง"))
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null",
                        "-"], capture_output=True, text=True).stderr
    m_i = re.findall(r"I:\s+(-?[\d\.]+) LUFS", e)
    m_p = re.findall(r"Peak:\s+(-?[\d\.]+) dBFS", e)
    if m_i:
        lufs = float(m_i[-1])
        result.setdefault("audio", {})["lufs"] = lufs
        if not -19.5 <= lufs <= -12.5:
            out.append(_issue("warn", "loudness", f"ความดังรวม {lufs:.1f} LUFS (แนะนำ -16 ถึง -14)"))
    if m_p:
        tp = float(m_p[-1])
        result.setdefault("audio", {})["true_peak"] = tp
        if tp > -0.5:
            out.append(_issue("error", "true_peak", f"True peak {tp:.1f} dBFS เสี่ยงเสียงแตก", fix="lower_gain"))
    return out


def auto_fix(plan, issues):
    """Apply automatic fixes; returns True when a re-render is warranted."""
    changed = False
    codes = {i["code"] for i in issues if i.get("fix")}
    if "lower_gain" in codes:
        plan["settings"]["music_db"] = float(plan["settings"].get("music_db", -26)) - 3
        changed = True
    if "drop_effect" in codes:   # a broken effect falls back to the plain shot rather than failing the export
        for i in issues:
            if i.get("fix") == "drop_effect":
                for seg in plan["segments"]:
                    if seg["id"] == i.get("seg"):
                        seg["effects"] = [e for e in seg.get("effects") or [] if e["id"] != i.get("effect")]
                        changed = True
    if codes & {"extend_clip"}:
        for seg in plan["segments"]:
            words = [w for w in seg["words"] if w["s"] is not None]
            if not seg.get("keep") or not words or not seg.get("clips"):
                continue
            seg["clips"][0][0] = round(min(seg["clips"][0][0], words[0]["s"] - 0.06), 3)
            seg["clips"][-1][1] = round(max(seg["clips"][-1][1], words[-1]["e"] + 0.1), 3)
            changed = True
    return changed
