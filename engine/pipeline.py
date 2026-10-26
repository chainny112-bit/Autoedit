"""End-to-end pipeline. One shared analysis per source video; any number of variants (editing plans) built from it.

  analyze_job   probe, denoise, transcribe, faces, chroma, (optional paid LLM)  -> analysis.json   [once]
  plan_variant  preset/settings + cut decisions + AI Director effect selection   -> variants/<v>/plan.json
  render_variant  render + QC (+ automatic fixes)                                -> variants/<v>/{preview,final}.mp4
"""
import colorsys
import json
import os
import shlex
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import copy
import time

from . import DATA_DIR, analyze as A, llm, media, planner, presets, projects, qc, render, thai, transcribe as T, vision
from .effects import selector as SEL, segmentation as SEG

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
SUB_EXT = {".srt", ".vtt"}


def load_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(p, data):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def assets_meta(job):
    meta = {}
    for a in job.get("assets", []):
        meta[a["name"]] = a
        if a.get("role") == "music":
            meta["__music__"] = a
    return meta


def reference_palette(paths):
    """Brand colours from reference images/logos: the dominant saturated hue becomes the primary accent,
    a clearly different hue covering even a small area (e.g. a logo's dot) becomes the secondary."""
    px = []
    for p in paths:
        try:
            im = Image.open(p).convert("RGBA")
            im.thumbnail((400, 400))
            a = np.asarray(im).reshape(-1, 4)
            px.append(a[a[:, 3] > 200][:, :3])  # ignore transparent areas of logos
        except Exception:
            continue
    if not px:
        return None
    arr = np.concatenate(px).astype(np.float32) / 255
    mx, mn = arr.max(1), arr.min(1)
    sat = (mx - mn) / (mx + 1e-6)
    sel = arr[(sat > 0.5) & (mx > 0.45)]
    if len(sel) < 30 or len(sel) < 0.02 * len(arr):  # mostly neutral (e.g. a white logo): keep current colours
        return None
    hsv = np.array([colorsys.rgb_to_hsv(*c) for c in sel[:: max(1, len(sel) // 6000)]])
    hist, edges = np.histogram(hsv[:, 0], 36, (0, 1))
    to_hex = lambda c: "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in c)

    def colour_of(bin_idx):
        lo, hi = edges[bin_idx], edges[bin_idx + 1]
        members = hsv[(hsv[:, 0] >= lo) & (hsv[:, 0] < hi)]
        return to_hex(colorsys.hsv_to_rgb(*np.median(members, 0)))

    k1 = int(hist.argmax())
    accent = colour_of(k1)
    # secondary: strongest bin at least ~60 degrees of hue away with >=0.3% of the colourful pixels
    dist = np.minimum(np.abs(np.arange(36) - k1), 36 - np.abs(np.arange(36) - k1))
    cand = np.where((dist >= 6) & (hist >= max(3, 0.003 * hist.sum())), hist, 0)
    if cand.max() > 0:
        accent2 = colour_of(int(cand.argmax()))
    else:  # single-colour reference: derive a neighbouring tone
        h, s_, v = colorsys.rgb_to_hsv(*[int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        accent2 = to_hex(colorsys.hsv_to_rgb((h + 0.06) % 1, s_, min(1, v * 1.15)))
    return {"accent": accent, "accent2": accent2, "share": round(float(len(sel) / len(arr)), 3)}


def generate_ai_images(job_dir, job, plan, log, allowed=False):
    """Optional: run a user-configured image generator for placeholder rows.

    AUTOEDIT_IMAGE_CMD is a command template with {prompt} and {out}, e.g.
      AUTOEDIT_IMAGE_CMD='python my_gen.py --prompt {prompt} --out {out}'
    """
    tmpl = os.environ.get("AUTOEDIT_IMAGE_CMD")
    if not tmpl:
        return 0
    if not allowed:
        log("ตัวสร้างภาพ AI พร้อมใช้ แต่ยังไม่ได้รับอนุญาตให้เรียก (อาจมีค่าใช้จ่าย) — คง Placeholder ไว้")
        return 0
    n = 0
    for row in plan["segments"]:
        b = row.get("broll") or {}
        if not row.get("keep") or b.get("kind") != "placeholder" or not b.get("prompt"):
            continue
        name = f"ai_{row['id']}.png"
        out = Path(job_dir) / "assets" / name
        cmd = tmpl.format(prompt=shlex.quote(b["prompt"]), out=shlex.quote(str(out)))
        log(f"สร้างภาพ AI สำหรับ {row['id']}: {b['prompt'][:80]}")
        try:
            subprocess.run(cmd, shell=True, check=True, timeout=600, capture_output=True)
        except Exception as e:
            log(f"⚠️ สร้างภาพ AI ไม่สำเร็จ ({row['id']}): {e} — คง Placeholder ไว้")
            continue
        if not out.exists() or out.stat().st_size < 1000:
            log(f"⚠️ ไม่พบไฟล์ภาพที่สร้าง ({out.name}) — คง Placeholder ไว้")
            continue
        job.setdefault("assets", []).append({"name": name, "path": str(out), "kind": "image", "source": "ai",
                                             "role": "broll", "tags": thai.content_words(thai.tokenize(row["text"]))})
        row["broll"] = {"kind": "asset", "asset": name, "source": "ai", "label": "ภาพสร้างด้วย AI",
                        "prompt": b["prompt"]}
        n += 1
    return n


STYLE_KEYS = set(presets.PresetModel.model_fields) - {"name", "description"}
CONTENT_KEYS = ("keep", "text", "highlight", "words", "word_level", "spelling", "cut_reason")
PERF = DATA_DIR / "perf.json"


# ---------------------------------------------------------------- analysis (shared by all variants)
def analyze_job(job_dir, job, log=print, progress=lambda p, m="": None):
    job_dir = Path(job_dir)
    st = {**planner.DEFAULT_SETTINGS, **job.get("settings", {})}
    src = job_dir / job["source"]
    progress(0.02, "ตรวจสอบไฟล์")
    info = media.probe(src)
    log(f"ต้นฉบับ: {info['width']}x{info['height']} {info['fps']}fps {info['duration']:.1f}s ({info['orientation']})"
        f"{'' if info['has_audio'] else ' — ไม่มีเสียง'}")
    if info["duration"] > 15 * 60:
        raise RuntimeError("วิดีโอยาวเกิน 15 นาที — ระบบออกแบบสำหรับคลิป 1–5 นาที")
    palette = None
    refs = [a["path"] for a in job.get("assets", []) if a.get("role") == "reference"]
    if refs:
        palette = reference_palette(refs)
        if palette:
            log(f"สีจากภาพอ้างอิง: {palette['accent']} / {palette['accent2']}")

    progress(0.08, "แยกเสียงพูดและลดเสียงรบกวน")
    wav = job_dir / "speech16k.wav"
    if info["has_audio"]:
        media.extract_audio(src, wav, 16000, denoise=st.get("denoise", True))
        silences, noise_db = media.detect_silences(wav)
        log(f"ตรวจช่วงเงียบ (threshold {noise_db:.1f} dB): {len(silences)} ช่วง")
    else:
        silences, noise_db = [], None
    mask = T.speech_mask_from_silences(silences, info["duration"])

    progress(0.15, "ถอดเสียงเป็นข้อความ")
    sub = next((a for a in job.get("assets", []) if a.get("role") == "transcript"), None)
    asr_meta = {}
    if sub:
        segments = T.segments_from_subtitles(sub["path"], mask)
        log(f"ใช้ Transcript จากไฟล์ {sub['name']}: {len(segments)} ประโยค (timestamp ระดับคำประมาณจากช่วงเสียงพูด)")
        asr_meta = {"engine": "subtitle-file"}
    elif not info["has_audio"]:
        raise RuntimeError("วิดีโอไม่มีเสียงและไม่ได้แนบไฟล์ซับ — ไม่สามารถสร้างซับได้")
    elif T.whisper_available():
        segments, asr_meta = T.transcribe_whisper(wav, st.get("asr_model", "small"), st.get("language", "th"), log=log)
        asr_meta["engine"] = f"faster-whisper/{st.get('asr_model', 'small')}"
        if not segments:
            raise RuntimeError("ไม่พบเสียงพูดในวิดีโอ")
    else:
        raise RuntimeError("ไม่มีระบบถอดเสียง (faster-whisper) — ติดตั้งด้วย `pip install faster-whisper` "
                           "หรือแนบไฟล์ซับ .srt/.vtt มากับวิดีโอ")

    progress(0.45, "วิเคราะห์ใบหน้า ฉาก และฉากเขียว")
    vis = vision.analyze(src, info, log=log)
    chroma = SEG.detect_chroma(src, info)
    chroma_info = None
    if max(chroma["green"], chroma["blue"]) > 0.35:
        kind = "green" if chroma["green"] >= chroma["blue"] else "blue"
        chroma_info = {"share": max(chroma.values()), "type": kind, "key": "0x00FF00" if kind == "green" else "0x0000FF"}
        log(f"พบฉาก{('เขียว' if kind == 'green' else 'น้ำเงิน')} ({chroma_info['share']:.0%} ของขอบภาพ) → Green Screen ใช้ Chroma key ได้")

    progress(0.62, "วิเคราะห์เนื้อหา")
    llm_rows, summary = {}, ""
    if llm.available() and st.get("use_llm") in ("on", True):
        try:
            tmp = copy.deepcopy(segments)
            A.classify_cuts(tmp, st, log=lambda *_: None)
            log("เรียก Claude API เพื่อวิเคราะห์โครงเรื่อง (ผู้ใช้อนุญาตแล้ว — มีค่าใช้จ่าย)")
            llm_rows, summary = llm.analyze(tmp, log=log)
            asr_meta["story_summary"] = summary
        except Exception as e:
            log(f"⚠️ วิเคราะห์ด้วย Claude ไม่สำเร็จ ({e}) — ใช้ heuristic แทน")
    elif llm.available():
        log("มี Claude API key แต่ยังไม่ได้อนุญาตให้เรียก (มีค่าใช้จ่าย) — ใช้การวิเคราะห์แบบกฎ")

    progress(0.8, "สร้างภาพตัวอย่าง")
    thumbs = job_dir / "thumbs"
    thumbs.mkdir(exist_ok=True)
    for seg in segments:
        try:
            media.thumbnail(src, (seg["start"] + seg["end"]) / 2, thumbs / f"{seg['id']}.jpg", 240)
        except Exception:
            pass
    info["_silences"] = silences
    analysis = {"info": info, "segments_raw": segments, "silences": silences, "vision": vis, "noise_db": noise_db,
                "asr": asr_meta, "llm_rows": llm_rows, "chroma": chroma_info, "palette": palette, "t": time.time()}
    save_json(job_dir / "analysis.json", analysis)
    progress(1.0, "วิเคราะห์เสร็จ")
    return analysis


# ---------------------------------------------------------------- variants
def variant_dir(job_dir, vid):
    d = Path(job_dir) / "variants" / vid
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_settings(job, variant):
    """settings = defaults <- job form settings <- variant preset <- variant overrides <- brand."""
    s = {**planner.DEFAULT_SETTINGS, **job.get("settings", {})}
    brand = job.get("brand") or {}
    pid = variant.get("preset_id")
    if pid:
        pre = presets.get(pid)
        if pre:
            s.update(presets.to_settings(pre, brand))
    s.update(variant.get("overrides") or {})
    return s


def plan_variant(job_dir, job, vid, log=print, carry_content=True):
    """(Re)build a variant's plan from the cached analysis — no re-transcription/re-detection."""
    job_dir = Path(job_dir)
    an = load_json(job_dir / "analysis.json")
    if not an:
        raise RuntimeError("ยังไม่มีผลการวิเคราะห์ — วิเคราะห์วิดีโอก่อน")
    variant = job["variants"][vid]
    st = resolve_settings(job, variant)
    if an.get("palette") and st.get("use_reference_colors") and not st.get("accent_locked") and not variant.get("preset_id"):
        st["accent"], st["accent2"] = an["palette"]["accent"], an["palette"]["accent2"]
    if an.get("chroma"):
        st["_chroma"] = an["chroma"]
    segments = copy.deepcopy(an["segments_raw"])
    A.classify_cuts(segments, st, log=log)
    info = dict(an["info"])
    info["_silences"] = an["silences"]
    plan = planner.build_plan(info, segments, an["vision"], st, job.get("assets", []), an.get("llm_rows") or {}, log=log)
    for row, seg in zip(plan["segments"], segments):
        row["trim_start"], row["trim_end"] = seg["trim_start"], seg["trim_end"]
    old = load_json(variant_dir(job_dir, vid) / "plan.json") if carry_content else None
    if old:   # keep the user's content edits (text/keep/highlight) when only the style changes
        olds = {s["id"]: s for s in old["segments"]}
        for row in plan["segments"]:
            o = olds.get(row["id"])
            if o and (o.get("_user_edited") or o.get("keep") != row.get("keep")):
                for k in CONTENT_KEYS:
                    if k in o:
                        row[k] = o[k]
                row["_user_edited"] = True
        A.build_clips(plan["segments"], an["silences"], info["duration"], st, {r["id"]: r.get("role") for r in plan["segments"]})
        for row in plan["segments"]:
            row["faces"] = [vision.face_in_range(an["vision"], c[0], c[1]) for c in row["clips"]]
            row["subs"] = planner.make_subs(row, st) if row.get("keep") else []
    if st.get("avoid_effects"):
        st["_avoid"] = st["avoid_effects"]
    SEL.direct(plan, st, job.get("assets", []), log=log)
    plan["analysis"] = {"asr": an.get("asr"), "noise_db": an.get("noise_db"), "face_detector": an["vision"].get("detector"),
                        "llm": bool(an.get("llm_rows")), "chroma": an.get("chroma")}
    plan["settings"] = st
    plan["estimated_duration"] = round(sum(c[1] - c[0] for r in plan["segments"] for c in r["clips"]), 2)
    n_ai = generate_ai_images(job_dir, job, plan, log, allowed=bool(st.get("allow_ai_images")))
    if n_ai:
        log(f"สร้างภาพ AI แล้ว {n_ai} ภาพ (ติดป้าย 'ภาพสร้างด้วย AI')")
    save_json(variant_dir(job_dir, vid) / "plan.json", strip_runtime(plan))
    return plan


def strip_runtime(plan):
    for s in plan["segments"]:
        for k in [k for k in s if k.startswith("_") and k not in ("_user_edited", "_fx_asset")]:
            s.pop(k)
    return plan


def update_plan(job_dir, vid, new_plan):
    """Apply user edits from the plan editor (text, keep, layout, effects, transitions...)."""
    from .effects import REGISTRY
    job_dir = Path(job_dir)
    vdir = variant_dir(job_dir, vid)
    old = load_json(vdir / "plan.json")
    an = load_json(job_dir / "analysis.json", {})
    mask = T.speech_mask_from_silences(an.get("silences", []), old["source"]["duration"])
    olds = {s["id"]: s for s in old["segments"]}
    for row in new_plan["segments"]:
        o = olds.get(row.get("id"))
        if o and (row.get("text", o["text"]).strip() != o["text"].strip() or row.get("keep") != o.get("keep")
                  or row.get("highlight") != o.get("highlight")):
            row["_user_edited"] = True
        # effects: validate ids and parameters
        intensity = new_plan.get("settings", old["settings"]).get("intensity", "medium")
        fx = []
        for e in row.get("effects") or []:
            eff = REGISTRY.get(e.get("id"))
            if eff:
                fx.append({"id": eff.id, "params": eff.clean_params(e.get("params"), intensity),
                           "reason": e.get("reason") or "ผู้ใช้เลือกเอง", "auto": bool(e.get("auto"))})
        row["effects"] = fx
        ti = row.get("transition_in") or {"id": "cut"}
        if ti.get("id") not in ("cut", "flash", "zoom_through"):
            ti = {"id": "cut"}
        ti.setdefault("reason", "ผู้ใช้เลือกเอง")
        row["transition_in"] = ti
        if any(REGISTRY[e["id"]].category == "panel" for e in fx) and row.get("layout") in ("full", "fit"):
            row["layout"] = "pip"
    keep_changed = any(o["keep"] != n.get("keep", o["keep"]) for o, n in zip(old["segments"], new_plan["segments"]))
    plan = planner.apply_edits(old, new_plan, mask)
    for row, o in zip(plan["segments"], old["segments"]):
        row.setdefault("trim_start", o.get("trim_start", o["start"]))
        row.setdefault("trim_end", o.get("trim_end", o["end"]))
        if not row.get("keep"):
            row["cut_reason"] = row.get("cut_reason") or "ผู้ใช้ตัดออก"
    if keep_changed or plan["settings"].get("pacing") != old["settings"].get("pacing"):
        roles = {r["id"]: r.get("role") for r in plan["segments"]}
        A.build_clips(plan["segments"], an.get("silences", []), old["source"]["duration"], plan["settings"], roles)
        for row in plan["segments"]:
            row["faces"] = [vision.face_in_range(an.get("vision"), c[0], c[1]) for c in row["clips"]]
    plan["estimated_duration"] = round(sum(c[1] - c[0] for r in plan["segments"] for c in r["clips"]), 2)
    for k in ("analysis", "direction"):
        if k in old:
            plan[k] = old[k]
    save_json(vdir / "plan.json", strip_runtime(plan))
    return plan


def plan_stats(plan):
    from collections import Counter
    from .effects import REGISTRY
    kept = [s for s in plan["segments"] if s.get("keep")]
    fx = Counter(e["id"] for s in kept for e in s.get("effects") or [])
    broll = sum(1 for s in kept if s.get("layout") in ("pip", "split", "broll_full"))
    mograph = sum(1 for s in kept if any(REGISTRY[e["id"]].category in ("panel", "overlay") for e in s.get("effects") or [])
                  or (s.get("broll") or {}).get("kind") in ("stat", "steps", "timeline", "keyword", "compare"))
    return {"duration": plan.get("estimated_duration"), "subtitle_mode": plan["settings"].get("subtitle_mode"),
            "subtitle_font": plan["settings"].get("subtitle_font"),
            "main_effects": [REGISTRY[e].name for e, _ in fx.most_common(4)], "effect_counts": dict(fx),
            "broll_segments": broll, "mograph_segments": mograph,
            "transitions": sum(1 for s in kept if (s.get("transition_in") or {}).get("id") not in (None, "cut")),
            "cut_segments": [{"id": s["id"], "text": s["text"], "reason": s.get("cut_reason")}
                             for s in plan["segments"] if not s.get("keep")],
            "segments_total": len(plan["segments"]), "segments_kept": len(kept),
            "direction": (plan.get("direction") or {}).get("summary", "")}


def _perf():
    return load_json(PERF, {"preview": 0.9, "final": 2.6, "mask": 2.2, "n": 0})


def record_perf(kind, seconds, out_dur, mask_secs=0):
    p = _perf()
    rate = max(0.1, (seconds - mask_secs * p["mask"]) / max(1.0, out_dur))
    p[kind] = round(0.7 * p[kind] + 0.3 * rate, 3)   # moving average calibrates estimates to this machine
    p["n"] = p.get("n", 0) + 1
    save_json(PERF, p)


def preflight(job_dir, job, vid, kind="preview"):
    """Before rendering: time estimate, disk space, external/paid APIs, effect requirements."""
    import shutil as _sh
    from . import llm as _llm
    from .effects import REGISTRY, capabilities as fx_caps
    plan = load_json(variant_dir(job_dir, vid) / "plan.json")
    if not plan:
        return {"ok": False, "errors": ["ยังไม่มี Editing Plan"]}
    p = _perf()
    caps = fx_caps()
    out_dur = plan.get("estimated_duration") or 0
    mask_secs = sum(c[1] - c[0] for s in plan["segments"] if s.get("keep")
                    for e in s.get("effects") or [] if e["id"] in render.MASK_EFFECTS for c in s["clips"])
    cores = os.cpu_count() or 4
    est = (out_dur * p[kind] + (mask_secs * p["mask"] if caps["segmentation"] else 0)) * max(0.5, 4 / cores)
    if kind == "preview":
        est *= 1.0
    need = int(out_dur * (1.2e6 if kind == "preview" else 4.5e6) + 50e6)
    free = _sh.disk_usage(job_dir).free
    warnings, errors = [], []
    if free < need:
        errors.append(f"พื้นที่ว่างไม่พอ: เหลือ {free / 1e9:.1f} GB ต้องการประมาณ {need / 1e9:.2f} GB")
    effects_needs = []
    for s in plan["segments"]:
        for e in s.get("effects") or []:
            eff = REGISTRY.get(e["id"])
            miss = [r for r in eff.enhanced_by if not caps.get(r)] if eff else []
            if miss:
                effects_needs.append(f"{eff.name} ({s['id']}): ไม่มี {', '.join(miss)} → ใช้ Fallback")
    apis = [{"name": "Claude API (วิเคราะห์เรื่อง)", "available": _llm.available(),
             "allowed": plan["settings"].get("use_llm") in ("on", True), "paid": True,
             "when": "ตอนวิเคราะห์ (ทำไปแล้ว)" if plan.get("analysis", {}).get("llm") else "ไม่ถูกเรียก"},
            {"name": "AI Image (AUTOEDIT_IMAGE_CMD)", "available": bool(os.environ.get("AUTOEDIT_IMAGE_CMD")),
             "allowed": bool(plan["settings"].get("allow_ai_images")), "paid": True,
             "when": "ตอนสร้างแผน เฉพาะ Placeholder" if os.environ.get("AUTOEDIT_IMAGE_CMD") else "ไม่ได้ตั้งค่า → ใช้ Placeholder"}]
    cached = len(list((Path(job_dir) / "cache" / "clips").glob("*.mkv"))) if (Path(job_dir) / "cache").exists() else 0
    return {"ok": not errors, "kind": kind, "estimate_seconds": round(est), "output_seconds": out_dur,
            "mask_seconds": round(mask_secs, 1), "disk_free_gb": round(free / 1e9, 1), "disk_need_gb": round(need / 1e9, 2),
            "segmentation": caps["segmentation_detail"], "apis": apis, "effect_fallbacks": effects_needs,
            "cached_clips": cached, "warnings": warnings, "errors": errors,
            "calibrated": p.get("n", 0) > 0}


def render_variant(job_dir, job, vid, preview=False, log=print, progress=lambda p, m="": None, cancel=lambda: False):
    job_dir = Path(job_dir)
    vdir = variant_dir(job_dir, vid)
    plan = load_json(vdir / "plan.json")
    if not plan:
        raise RuntimeError("ยังไม่มี Editing Plan — วิเคราะห์วิดีโอก่อน")
    plan["source"]["path"] = str((job_dir / job["source"]).resolve())
    meta = assets_meta(job)
    attempt = 0
    t_start = time.time()
    while True:
        res = render.render(vdir, plan, meta, preview=preview, log=log, progress=progress,
                            cache_dir=job_dir / "cache", cancel=cancel)
        progress(0.96, "ตรวจสอบคุณภาพก่อนส่งงาน")
        issues, info = qc.check(res, plan, preview)
        errs = [i for i in issues if i["level"] == "error"]
        log(f"QC: error {len(errs)}, warning {sum(i['level'] == 'warn' for i in issues)}")
        if errs and attempt == 0 and qc.auto_fix(plan, errs):
            log("พบข้อผิดพลาดที่แก้อัตโนมัติได้ — ลดความซับซ้อน/แก้แผนแล้วเรนเดอร์ใหม่")
            save_json(vdir / "plan.json", strip_runtime(plan))
            attempt += 1
            continue
        break
    mask_secs = sum(r.get("mask", {}).get("frames", 0) / res["fps"] for r in res["effects_report"]
                    if r.get("effect") == "segmentation" and r.get("mask"))
    if not res.get("reused_clips"):
        record_perf("preview" if preview else "final", time.time() - t_start, res["duration"], mask_secs)
    report = {"preview": preview, "issues": issues, "info": info, "duration": res["duration"], "fps": res["fps"],
              "size": res["size"], "attempts": attempt + 1, "profile": res["profile"],
              "effects_report": res["effects_report"], "reused_clips": res["reused_clips"],
              "audio": res.get("audio"), "seconds": round(time.time() - t_start, 1),
              "timeline": [{k: it[k] for k in ("seg", "ci", "a", "d", "out", "layout", "zoom")} for it in res["items"]]}
    save_json(vdir / f"qc_{'preview' if preview else 'final'}.json", report)
    return report
