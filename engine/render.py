"""Timeline assembly and rendering with FFmpeg."""
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import FONTS_DIR, graphics as G, media, thai
from . import effects as FX
from .effects.camera import motion_chain, zoom_chain

W, H = 1080, 1920
CAMERA_OR_COMPOSITE = {e.id for e in FX.REGISTRY.values() if e.category in ("camera", "composite")}
MASK_EFFECTS = ("frame_break", "green_screen", "couch_wall", "vertigo", "cover_story")
PROFILES = {   # export profiles: scale, crf, x264 preset, audio bitrate
    "1080p_high": {"S": 1.0, "crf": 18, "preset": "medium", "ab": "192k", "label": "1080×1920 คุณภาพสูง"},
    "1080p_fast": {"S": 1.0, "crf": 21, "preset": "veryfast", "ab": "160k", "label": "1080×1920 เร็ว/ไฟล์เล็ก"},
    "720p": {"S": 720 / 1080, "crf": 21, "preset": "medium", "ab": "160k", "label": "720×1280 อัปโหลดเร็ว"},
    "preview": {"S": 0.5, "crf": 28, "preset": "ultrafast", "ab": "128k", "label": "Preview 540×960"},
}
CACHE_VERSION = 3


class Cancelled(RuntimeError):
    pass
PANEL_H = 960
SFX_FILES = ("whoosh", "pop", "hit")


# ---------------------------------------------------------------- geometry
def presenter_crop(src_w, src_h, face, tw, th, zoom=1.0, face_y=0.40):
    """Crop rectangle (source px) for a target region tw x th, centred on the face.

    Returns (x, y, cw, ch, face_out) where face_out is the face box in region coordinates.
    """
    a = tw / th
    if src_w / src_h > a:
        ch, cw = src_h, src_h * a
    else:
        cw, ch = src_w, src_w / a
    if face:
        # never zoom so far that the face fills more than ~55% of the crop height
        zoom = min(zoom, max(1.0, ch * 0.55 / max(1, face[3] * src_h)))
    cw, ch = cw / zoom, ch / zoom
    if face:
        fx, fy = face[0] * src_w, face[1] * src_h
        x, y = fx - cw / 2, fy - ch * face_y
    else:
        x, y = (src_w - cw) / 2, (src_h - ch) / 2
    x = min(max(0, x), src_w - cw)
    y = min(max(0, y), src_h - ch)
    cw, ch = int(cw) // 2 * 2, int(ch) // 2 * 2
    x, y = int(x) // 2 * 2, int(y) // 2 * 2
    face_out = None
    if face:
        fw, fh = face[2] * src_w, face[3] * src_h
        sx, sy = tw / cw, th / ch
        fx0, fy0 = face[0] * src_w - fw / 2, face[1] * src_h - fh / 2
        face_out = [(fx0 - x) * sx, (fy0 - y) * sy, (fx0 + fw - x) * sx, (fy0 + fh - y) * sy]
    return x, y, cw, ch, face_out


def build_timeline(plan, fps):
    src = plan["source"]
    zi = float(plan["settings"].get("zoom_intensity", 1.15))
    zooms = {"none": 1.0, "punch": zi, "close": 1 + (zi - 1) * 2.3}
    items, out_t = [], 0.0
    kept = [s for s in plan["segments"] if s.get("keep") and s.get("clips")]
    for si, seg in enumerate(kept):
        fx_ids = {e["id"] for e in seg.get("effects") or []}
        has_motion = bool(fx_ids & CAMERA_OR_COMPOSITE)
        t_off = 0.0
        nxt = kept[si + 1] if si + 1 < len(kept) else None
        for ci, (a, b) in enumerate(seg["clips"]):
            frames = max(2, int(round((b - a) * fps)))
            d = frames / fps
            layout = seg.get("layout", "full")
            zoom = seg.get("zoom", "none")
            if layout == "full" and ci % 2 == 1 and not has_motion:  # jump cut inside a sentence: alternate framing
                zoom = "punch" if zoom == "none" else "none"
            face = (seg.get("faces") or [None] * (ci + 1))[ci] if ci < len(seg.get("faces") or []) else None
            if layout in ("full", "fit"):
                if layout == "fit" and face:
                    layout = "full"
                region = (0, 0, W, H)
                fy = 0.40
            elif layout in ("pip", "split"):
                region = (0, PANEL_H, W, H - PANEL_H)
                fy = 0.45
                zoom = "punch" if zoom == "none" and not has_motion else zoom
            else:
                region = None
                fy = 0.4
            item = {"seg": seg["id"], "ci": ci, "a": round(a, 4), "d": round(d, 4), "out": round(out_t, 4),
                    "layout": layout, "zoom": zoom, "region": region, "face_out": None, "t_off": round(t_off, 4),
                    "first": ci == 0, "last": ci == len(seg["clips"]) - 1}
            ti = seg.get("transition_in") or {}
            if ci == 0 and si > 0 and ti.get("id") == "zoom_through":
                item["trans_in"] = ti.get("params") or {}
            to = (nxt or {}).get("transition_in") or {}
            if ci == len(seg["clips"]) - 1 and to.get("id") == "zoom_through":
                item["trans_out"] = to.get("params") or {}
            if region and layout != "fit":
                x, y, cw, ch, fo = presenter_crop(src["width"], src["height"], face, region[2], region[3],
                                                  zooms.get(zoom, 1.0), fy)
                item["crop"] = [x, y, cw, ch]
                if fo:
                    item["face_out"] = [fo[0] + region[0], fo[1] + region[1], fo[2] + region[0], fo[3] + region[1]]
            items.append(item)
            out_t += d
            t_off += d
    return items, round(out_t, 4)


def src_to_out(items_by_seg, seg_id, t, side):
    """Map a source timestamp inside a segment to output time (snapping across removed pauses)."""
    its = items_by_seg.get(seg_id, [])
    if not its:
        return None
    for it in its:
        if it["a"] <= t <= it["a"] + it["d"]:
            return it["out"] + (t - it["a"])
    if t < its[0]["a"]:
        return its[0]["out"]
    for k, it in enumerate(its):
        end = it["a"] + it["d"]
        nxt = its[k + 1] if k + 1 < len(its) else None
        if nxt and end < t < nxt["a"]:
            return it["out"] + it["d"] if side == "end" else nxt["out"]
    last = its[-1]
    return last["out"] + last["d"]


# ---------------------------------------------------------------- graphics
def subtitle_y(item, size, layout):
    cands = {"full": [1290, 1440, 1140], "fit": [1350, 1460], "pip": [1050, 1460, 1230],
             "split": [1050, 1460, 1230], "broll_full": [1350]}.get(layout, [1290])
    f = item.get("face_out")
    for y in cands:
        top, bot = y - size * 0.8, y + size * 0.8
        if not f or bot < f[1] - 10 or top > f[3] + 10:
            return y
    return cands[0]


def build_ass(plan, items, total, assets_meta, feats=None, report=None):
    from types import SimpleNamespace
    st = plan["settings"]
    sc = G.Script(st)
    by_seg = {}
    for it in items:
        by_seg.setdefault(it["seg"], []).append(it)
    size = int(st.get("subtitle_size", 92))
    feats = feats or {}
    kept = [s for s in plan["segments"] if by_seg.get(s["id"])]
    for si, seg in enumerate(kept):
        its = by_seg[seg["id"]]
        t0, t1 = its[0]["out"], its[-1]["out"] + its[-1]["d"]
        layout = its[0]["layout"]
        panel = (0, 0, W, PANEL_H) if layout in ("pip", "split") else (0, 0, W, H)
        b = seg.get("broll") or {"kind": "none"}
        fx = [(FX.get(e["id"]), e) for e in seg.get("effects") or [] if FX.get(e["id"])]
        panel_fx = any(eff.category == "panel" for eff, _ in fx)

        def word_out(i, seg=seg, t0=t0):
            if i is None or i >= len(seg["words"]) or seg["words"][i]["s"] is None:
                return t0
            return src_to_out(by_seg, seg["id"], seg["words"][i]["s"], "start")

        if layout in ("pip", "split"):
            sc.divider(t0, t1)
        if layout == "broll_full":
            sc.frame(t0, t1, 40, 140, 1000, 1640)
        k = None if panel_fx else b.get("kind")   # a panel effect replaces the basic b-roll graphic
        g0 = t0 + 0.05
        if k == "stat":
            sc.stat(g0, t1, b["value"], b.get("unit", ""), b.get("caption", ""), b.get("source_note", ""), panel,
                    t_spoken=word_out(b.get("word_index")) - 0.15)
            if layout in ("pip", "split"):
                sc.label(g0, t1, "ข้อมูลจากบทพูด")
        elif k == "timeline":
            sc.timeline(g0, t1, b["year"], b.get("caption", ""), panel)
        elif k == "steps":
            times = [word_out(i) for i in b.get("word_index", [])] or [g0] * len(b["items"])
            sc.steps(g0, t1, b["items"], times, panel)
        elif k == "keyword":
            sc.keyword(g0, t1, b.get("text") or "", panel)
        elif k == "compare":
            sc.compare(g0, t1, b.get("left", ""), b.get("right", ""), panel)
        elif k == "placeholder":
            sc.placeholder(g0, t1, b.get("description", ""), b.get("prompt", ""), panel)
            sc.label(g0, t1, "ภาพจำลอง · ยังไม่ได้สร้างภาพ")
        elif k == "asset":
            meta = assets_meta.get(b.get("asset"), {})
            lab = b.get("label") or ("ภาพสร้างด้วย AI" if meta.get("source") == "ai" else "ภาพประกอบ")
            if st.get("ai_label", True) or meta.get("source") != "ai":
                sc.label(g0, t1, lab)
        sub_y0 = subtitle_y(its[0], size, layout)
        if seg.get("title") and layout in ("full", "fit") and seg.get("title_style") != "effect" and \
                not any(e["id"] in ("glassy_type", "cover_story") for e in seg.get("effects") or []):
            sc.title_card(t0 + 0.05, min(t1, t0 + 2.8), seg["title"], y=_title_y(its[0], sub_y0))
        # subtitles
        phrases = []
        for p in seg.get("subs") or []:
            s_ = src_to_out(by_seg, seg["id"], p["s"], "start")
            e_ = src_to_out(by_seg, seg["id"], p["e"], "end")
            if s_ is None or e_ is None or e_ - s_ < 0.05:
                continue
            parts = []
            for w in p["parts"]:
                ws = src_to_out(by_seg, seg["id"], w["s"], "start") if w["s"] is not None else None
                parts.append({**w, "s": ws})
            phrases.append({**p, "s": s_, "e": min(e_, t1), "parts": parts})
        placed = []
        for p in phrases:  # place each phrase relative to the item it starts in
            it = next((i for i in its if i["out"] <= p["s"] < i["out"] + i["d"]), its[0])
            y = subtitle_y(it, size, layout)
            sc.subtitles([p], y, size, st.get("subtitle_mode", "keyword"))
            fnt = st.get("subtitle_font") if st.get("subtitle_font") in G.FONT_FILES else "Kanit ExtraBold"
            placed.append({**p, "y": y, "font": fnt, "size": G.fit_size(p["text"], fnt, size,
                                                                         G.SAFE["right"] - G.SAFE["left"] - 40)})
        # effect overlays
        nxt = [x for x in kept[si + 1: si + 5]]
        ox = SimpleNamespace(t0=t0, t1=t1, seg=seg, items=its, word_out=word_out, layout=layout,
                             face=its[0].get("face_out"), sub_y=sub_y0, sub_size=size, phrases=placed, settings=st,
                             feat=feats.get(seg["id"], {}), rt=seg.get("_runtime", {}), report=report,
                             cover_lines=[x.get("title") or thai.key_clause(x["text"], x.get("highlight") or [], 26)
                                          for x in nxt])
        for eff, e in fx:
            if hasattr(eff, "overlay"):
                try:
                    eff.overlay(sc, eff.clean_params(e.get("params"), st.get("intensity", "medium")), ox)
                except Exception as ex:   # one broken overlay must not sink the render
                    if report is not None:
                        report.append({"seg": seg["id"], "effect": eff.id, "status": "failed",
                                       "msg": f"กราฟิกผิดพลาด: {ex}"})
        # transition graphics at the cut into this segment
        ti = seg.get("transition_in") or {}
        if si > 0 and ti.get("id") == "zoom_through":
            zt = FX.get("zoom_through")
            zt.overlay_cut(sc, zt.clean_params(ti.get("params"), st.get("intensity", "medium")), t0)
        elif si > 0 and ti.get("id") == "flash":
            sc.shape(t0 - 0.04, t0 + 0.16, 0, 0, "m 0 0 l 1080 0 l 1080 1920 l 0 1920", fill=sc.primary,
                     fill_a=0x50, layer=41, extra="\\fad(30,130)")
    return sc


def _title_y(item, sub_y=1290, half_h=95):
    f = item.get("face_out")
    y = 330
    if not f or f[1] > y + half_h + 10:
        return y
    below = f[3] + half_h + 20
    if below + half_h < sub_y - 70:
        return below
    return max(G.SAFE["top"] + half_h, f[1] - half_h - 20) if f[1] - 2 * half_h - 20 > G.SAFE["top"] else y


# ---------------------------------------------------------------- generated media
def make_background(path, accent="#BC0000", w=1200, h=2200):
    if Path(path).exists():
        return path
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w * 0.5) / w) ** 2 + ((yy - h * 0.35) / h) ** 2)
    base = np.clip(1 - r * 1.6, 0, 1)[..., None] * np.array([22, 20, 20]) + np.array([6, 6, 7])
    acc = np.array([int(accent[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    g1 = np.exp(-(((xx - w * 0.85) / (w * 0.35)) ** 2 + ((yy - h * 0.12) / (h * 0.2)) ** 2))[..., None]
    g2 = np.exp(-(((xx - w * 0.1) / (w * 0.3)) ** 2 + ((yy - h * 0.75) / (h * 0.2)) ** 2))[..., None]
    img = base + acc * (0.22 * g1 + 0.12 * g2)
    img += np.random.default_rng(1).normal(0, 2.0, img.shape)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1)).save(path)
    return path


def _env(n, sr, a, r):
    e = np.ones(n, np.float32)
    na, nr = int(a * sr), int(r * sr)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr) ** 2
    return e


def synth_sfx(kind, sr=48000):
    rng = np.random.default_rng({"whoosh": 1, "pop": 2, "hit": 3}[kind])
    if kind == "whoosh":
        n = int(0.55 * sr)
        noise = rng.normal(0, 1, n).astype(np.float32)
        out, y = np.zeros(n, np.float32), 0.0
        cut = np.concatenate([np.linspace(0.01, 0.25, n // 2), np.linspace(0.25, 0.02, n - n // 2)])
        for i in range(n):  # sweeping one-pole low-pass
            y += cut[i] * (noise[i] - y)
            out[i] = y
        out *= np.sin(np.linspace(0, math.pi, n)) ** 1.5
    elif kind == "pop":
        n = int(0.16 * sr)
        t = np.arange(n) / sr
        f = 880 * np.exp(-t * 8)
        out = np.sin(2 * math.pi * np.cumsum(f) / sr) * np.exp(-t * 28)
        out[: int(0.003 * sr)] += rng.normal(0, 0.4, int(0.003 * sr))
    else:  # cinematic low hit
        n = int(1.1 * sr)
        t = np.arange(n) / sr
        f = 70 * np.exp(-t * 1.5) + 38
        out = np.sin(2 * math.pi * np.cumsum(f) / sr) * np.exp(-t * 3.2)
        tr = rng.normal(0, 1, n) * np.exp(-t * 40)
        out = out + 0.35 * tr
    out = out / (np.abs(out).max() + 1e-9)
    return out.astype(np.float32)


def synth_music(duration, sr=48000, seed=7):
    """Royalty-free ambient pad generated here (dark minor progression + soft pulse)."""
    n = int(duration * sr) + sr
    t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    chords = [(110.0, 130.81, 164.81), (87.31, 110.0, 130.81), (73.42, 87.31, 110.0), (82.41, 103.83, 123.47)]
    bar = 8.0
    for k in range(int(duration // bar) + 2):
        a, b = int(k * bar * sr), min(n, int((k + 1) * bar * sr + 1.5 * sr))
        if a >= n:
            break
        tt = t[a:b] - k * bar
        env = np.minimum(1, tt / 2.0) * np.clip((bar + 1.5 - tt) / 1.5, 0, 1)
        for f in chords[k % 4]:
            for det in (0.997, 1.0, 1.004):
                out[a:b] += 0.05 * env * np.sin(2 * math.pi * f * det * tt + det * 7)
            out[a:b] += 0.02 * env * np.sin(2 * math.pi * f * 2 * tt)
    beat = 60 / 70
    pulse_t = (t % beat)
    out += 0.12 * np.sin(2 * math.pi * 50 * pulse_t) * np.exp(-pulse_t * 9) * (np.sin(2 * math.pi * t / 32) * 0.5 + 0.5)
    out *= np.minimum(1, t / 2.0) * np.clip((duration - t) / 2.5, 0, 1)
    return (out / (np.abs(out).max() + 1e-9) * 0.7).astype(np.float32)


# ---------------------------------------------------------------- rendering
def _panel_input(seg, job_dir, assets_meta, bg_png, d, pw, ph):
    """Returns (ffmpeg input args, filter for the panel input producing pw x ph)."""
    b = seg.get("broll") or {}
    meta = assets_meta.get(b.get("asset")) if b.get("kind") == "asset" else None
    cover = (f"scale={pw * 1.12:.0f}:{ph * 1.12:.0f}:force_original_aspect_ratio=increase,"
             f"crop={pw}:{ph}:x='(iw-ow)/2+(iw-ow)/2*sin(t*0.35)':y='(ih-oh)/2+(ih-oh)/3*sin(t*0.27)'")
    if meta and Path(meta["path"]).exists():
        if meta["kind"] == "video":
            return (["-stream_loop", "-1", "-t", f"{d:.4f}", "-i", meta["path"]],
                    cover + ",eq=contrast=1.06:saturation=1.05:brightness=-0.03")
        return (["-loop", "1", "-framerate", "30", "-t", f"{d:.4f}", "-i", meta["path"]],
                cover + ",eq=contrast=1.06:saturation=1.05:brightness=-0.03")
    return (["-loop", "1", "-framerate", "30", "-t", f"{d:.4f}", "-i", str(bg_png)], cover)


def _n_inputs(args):
    return sum(1 for a in args if a == "-i")


def render_clip(item, seg, plan, work, out_path, fps, S, assets_meta, bg_png, cache, report, log=None, crf=16,
                preset="veryfast", mask=None):
    """Render one timeline item. Layer order: presenter -> (composite | camera motion) -> grade -> layout/panel
    -> post effects -> transition ramp."""
    src = plan["source"]
    st = plan["settings"]
    intensity = st.get("intensity", "medium")
    w, h = int(W * S) // 2 * 2, int(H * S) // 2 * 2
    ph = int(PANEL_H * S) // 2 * 2
    d = item["d"]
    grade = "eq=contrast=1.05:saturation=1.04,colorbalance=rs=0.02:gs=0.0:bs=-0.03:rh=0.02:bh=-0.02"
    if st.get("vignette", True):
        grade += ",vignette=angle=PI/6"
    args = ["-ss", f"{item['a']:.4f}", "-t", f"{d:.4f}", "-i", src["path"]]
    layout = item["layout"]
    fx = [(FX.get(e["id"]), FX.get(e["id"]).clean_params(e.get("params"), intensity))
          for e in seg.get("effects") or [] if FX.get(e["id"])]
    rw, rh = (w, h) if layout in ("full", "broll_full", "fit") else (w, h - ph)
    face = None
    if item.get("face_out"):
        fo = item["face_out"]
        oy = 0 if layout in ("full", "fit") else PANEL_H
        face = [fo[0] * S, (fo[1] - oy) * S, fo[2] * S, (fo[3] - oy) * S]
    cx = FX.ClipCtx(W=w, H=h, S=S, d=d, t_off=item["t_off"], seg_dur=sum(c[1] - c[0] for c in seg["clips"]),
                    fps=fps, item=item, seg=seg, settings=st, intensity=intensity, work=Path(work), cache=Path(cache),
                    assets=assets_meta, bg_png=str(bg_png), rw=rw, rh=rh, face=face, is_first=item["first"],
                    is_last=item["last"], mask_ok=bool(mask), report=report)
    fc = []
    if layout == "fit":
        fc.append(f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"boxblur=24:3,eq=brightness=-0.18:saturation=0.8[bg];"
                  f"[b]scale={w}:-2:flags=lanczos,{grade}[fg];[bg][fg]overlay=0:(H-h)/2,setsar=1[v]")
    elif layout != "broll_full":
        x, y, cw, ch = item["crop"]
        fc.append(f"[0:v]crop={cw}:{ch}:{x}:{y},scale={rw}:{rh}:flags=lanczos,setsar=1[pres]")
        if mask:
            args += ["-i", str(mask)]
            fc.append(f"[{_n_inputs(args) - 1}:v]setpts=PTS-STARTPTS[mask]")
        comp = None
        for eff, p in fx:
            if hasattr(eff, "composite"):
                r = eff.composite(p, cx, _n_inputs(args))
                if r:
                    comp = (eff, r)
                    break
                if eff.id in MASK_EFFECTS and eff.id != "cover_story":
                    report.append({"seg": seg["id"], "effect": eff.id, "status": "fallback", "msg": eff.fallback})
        if comp:
            eff, (cargs, graph) = comp
            args += cargs
            fc.append(graph)
            fc.append(f"[v]{grade}[vp]")
            how = ("Chroma key จากฉากเขียว/น้ำเงินจริง" if eff.id == "green_screen" and not mask
                   else "compositing ด้วย mask ตัวบุคคล" if mask else "compositing")
            report.append({"seg": seg["id"], "effect": eff.id, "status": "rendered", "msg": how})
        else:
            if mask:
                fc.append("[mask]nullsink")
            motions = []
            for eff, p in fx:
                if hasattr(eff, "camera"):
                    m = eff.camera(p, cx)
                    if m:
                        motions.append(m)
                        report.append({"seg": seg["id"], "effect": eff.id, "status": "rendered",
                                       "msg": "camera motion" + (" (จำลอง)" if eff.implementation == "simulation" else "")})
            chain = motion_chain(motions, cx)
            fc.append(f"[pres]{chain + ',' if chain else ''}{grade}[vp]")
        if layout in ("pip", "split"):
            pan = None
            for eff, p in fx:
                if hasattr(eff, "panel"):
                    pan = eff.panel(p, cx, _n_inputs(args), w, ph)
                    if pan:
                        report.append({"seg": seg["id"], "effect": eff.id, "status": "rendered", "msg": "panel"})
                        break
            if pan:
                args += pan[0]
                fc.append(pan[1])
            else:
                pin, pf = _panel_input(seg, work, assets_meta, bg_png, d, w, ph)
                i = _n_inputs(args)
                args += pin
                fc.append(f"[{i}:v]{pf},setsar=1[panel]")
            fc.append(f"[panel]fps={fps},setsar=1[top];[top][vp]vstack[v0]")
        else:
            fc.append("[vp]null[v0]")
    else:  # broll_full
        pan = None
        for eff, p in fx:
            if hasattr(eff, "panel"):
                pan = eff.panel(p, cx, _n_inputs(args), w, h)
                if pan:
                    break
        if pan:
            args += pan[0]
            fc.append(pan[1] + ";[panel]setsar=1[v0]")
        else:
            pin, pf = _panel_input(seg, work, assets_meta, bg_png, d, w, h)
            i = _n_inputs(args)
            args += pin
            fc.append(f"[{i}:v]{pf},setsar=1[v0]")
    for eff, p in fx:
        if eff.category == "panel" and layout not in ("pip", "split", "broll_full"):
            report.append({"seg": seg["id"], "effect": eff.id, "status": "skipped",
                           "msg": f"Layout '{layout}' ไม่มีพาเนลให้แสดงเอฟเฟกต์นี้ — เปลี่ยน Layout เป็นแบ่งจอ"})
    cur = "v" if layout == "fit" else "v0"
    for eff, p in fx:   # post-processing on the finished frame (e.g. glass blur)
        if hasattr(eff, "post"):
            g = eff.post(p, cx)
            if g:
                fc.append(g.replace("[vin]", f"[{cur}]").replace("[vout]", "[vpost]"))
                cur = "vpost"
                report.append({"seg": seg["id"], "effect": eff.id, "status": "rendered", "msg": "เบลอฉากหลังกระจกจริง"})
    # zoom-through transition ramps on the whole frame
    zt = FX.get("zoom_through")
    ramps = []
    tcx = FX.ClipCtx(W=w, H=h, S=S, d=d, t_off=0, seg_dur=d, fps=fps, item=item, seg=seg, settings=st,
                     intensity=intensity, work=Path(work), cache=Path(cache), assets=assets_meta, bg_png=str(bg_png),
                     rw=w, rh=h, face=None, report=report)
    if item.get("trans_in") is not None and d > 0.5:
        ramps.append(zt.ramp_in(zt.clean_params(item["trans_in"], intensity), tcx))
    if item.get("trans_out") is not None and d > 0.5:
        ramps.append(zt.ramp_out(zt.clean_params(item["trans_out"], intensity), tcx))
    if ramps:
        fc.append(f"[{cur}]{zoom_chain(w, h, '*'.join(ramps), 0.5, 0.45)}[vz]")
        cur = "vz"
    fc.append(f"[{cur}]fps={fps},format=yuv420p,trim=duration={d:.4f}[vo]")
    graph = ";".join(fc)
    if src["has_audio"]:
        fo = max(0.0, d - 0.03)
        graph += (f";[0:a]aresample=48000,aformat=channel_layouts=mono,"
                  f"afade=t=in:d=0.012,afade=t=out:st={fo:.4f}:d=0.03,apad,atrim=duration={d:.4f}[ao]")
        amap = ["-map", "[ao]"]
    else:
        args += ["-f", "lavfi", "-t", f"{d:.4f}", "-i", "anullsrc=r=48000:cl=mono"]
        amap = ["-map", f"{_n_inputs(args) - 1}:a"]
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args, "-filter_complex", graph,
           "-map", "[vo]", *amap, "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-g", str(int(fps * 2)),
           "-c:a", "pcm_s16le", "-ar", "48000", "-t", f"{d:.4f}", str(Path(out_path).resolve())]
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if p.returncode != 0:
        raise media.ToolError(f"ffmpeg (clip {seg['id']}/{item['ci']}) failed:\n" +
                              "\n".join(p.stderr.strip().splitlines()[-12:]))


def _clip_key(item, seg, plan, S, fps, crf, preset, mask_meta, assets_meta):
    src = Path(plan["source"]["path"])
    stt = src.stat()
    seg_vis = {k: seg.get(k) for k in ("layout", "zoom", "effects", "broll", "transition_in", "highlight", "title",
                                       "text", "_fx_asset")}
    seg_vis["clips"] = seg.get("clips")
    st = {k: plan["settings"].get(k) for k in ("accent", "accent2", "vignette", "intensity", "brand_name")}
    used = sorted((a["name"], Path(a["path"]).stat().st_size) for a in assets_meta.values()
                  if isinstance(a, dict) and a.get("path") and Path(a["path"]).exists() and a.get("role") == "broll")
    blob = json.dumps([CACHE_VERSION, str(src), stt.st_size, int(stt.st_mtime), item, seg_vis, st, S, fps, crf, preset,
                       mask_meta, used], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:24]


def render(job_dir, plan, assets_meta, preview=False, log=print, progress=lambda p, m="": None, cache_dir=None,
           profile=None, cancel=lambda: False):
    """Render a plan into job_dir/{preview|final}.mp4. job_dir is the variant directory; cache_dir is shared
    between variants (clips, masks, generated assets) so identical clips are rendered once."""
    from .effects import segmentation as SEG
    from .effects.overlays import GlassyType
    from .effects.selector import features
    job_dir = Path(job_dir).resolve()
    cache = Path(cache_dir or job_dir / "cache").resolve()
    (cache / "clips").mkdir(parents=True, exist_ok=True)
    st = plan["settings"]
    src = plan["source"]
    fps = float(st.get("fps") if str(st.get("fps", "source")).replace(".", "").isdigit() else src["fps"])
    fps = min(60.0, max(15.0, fps))
    prof = PROFILES["preview" if preview else (profile or st.get("export_profile") or "1080p_high")]
    S = prof["S"]
    name = "preview" if preview else "final"
    work = job_dir / f"work_{name}"
    work.mkdir(parents=True, exist_ok=True)
    for s in plan["segments"]:
        s["_runtime"] = {}
    items, total = build_timeline(plan, fps)
    if not items:
        raise RuntimeError("ไม่มีช่วงใดถูกเก็บไว้ในแผน — เปิด 'เก็บ' อย่างน้อยหนึ่งประโยค")
    bg_png = make_background(cache / f"bg_{st.get('accent', '#BC0000').lstrip('#')}.png", st.get("accent", "#BC0000"))
    segs = {s["id"]: s for s in plan["segments"]}
    size = int(st.get("subtitle_size", 92))
    by_seg = {}
    for it in items:
        by_seg.setdefault(it["seg"], []).append(it)
    for sid, its in by_seg.items():   # per-segment geometry shared by clip hooks and overlays
        if any(e["id"] == "glassy_type" for e in segs[sid].get("effects") or []):
            segs[sid]["_runtime"]["glass"] = GlassyType.rect(segs[sid], its[0].get("face_out"),
                                                             subtitle_y(its[0], size, its[0]["layout"]))
    report = []
    seg_ok, seg_why = SEG.status()
    clip_paths, reused = [], 0
    log(f"เรนเดอร์ {name}: {len(items)} คลิป, ความยาว {total:.1f}s, {int(W * S)}x{int(H * S)} @ {fps:g}fps")
    for k, it in enumerate(items):
        if cancel():
            raise Cancelled("ผู้ใช้ยกเลิกงาน — คลิปที่เรนเดอร์แล้วถูกเก็บใน cache เริ่มใหม่จะทำต่อจากเดิม")
        seg = segs[it["seg"]]
        mask, mask_meta = None, None
        wants_mask = it["layout"] == "full" and any(
            e["id"] in MASK_EFFECTS and not (e["id"] == "cover_story" and not it["first"])
            for e in seg.get("effects") or [])
        if wants_mask and (st.get("_chroma") or {}).get("share", 0) > 0.35 and \
                all(e["id"] == "green_screen" for e in seg.get("effects") or [] if e["id"] in MASK_EFFECTS):
            wants_mask = False   # real chroma key; no segmentation needed
        if wants_mask:
            if not seg_ok:
                report.append({"seg": seg["id"], "effect": "segmentation", "status": "fallback",
                               "msg": f"แยกตัวบุคคลไม่ได้: {seg_why}"})
            else:
                progress(0.03 + 0.67 * k / len(items), f"แยกตัวบุคคล (mask) คลิป {k + 1}/{len(items)}")
                mpath, meta = SEG.clip_mask(src["path"], it["a"], it["d"], it["crop"], fps, cache / "masks")
                mask_meta = meta
                if mpath and meta.get("ok"):
                    mask = mpath
                    report.append({"seg": seg["id"], "effect": "segmentation", "status": "rendered",
                                   "msg": f"mask ผ่าน QC (ขอบไม่ชัด {meta['uncertain']:.0%}, ความนิ่ง IoU {meta['iou']:.2f})",
                                   "mask": meta})
                else:
                    report.append({"seg": seg["id"], "effect": "segmentation", "status": "fallback",
                                   "msg": "mask ไม่ผ่าน QC → ใช้ fallback: " + (meta or {}).get("reason", ""),
                                   "mask": meta})
        key = _clip_key(it, seg, plan, S, fps, prof["crf"] if not preview else 28, prof["preset"], mask_meta,
                        assets_meta)
        cpath = cache / "clips" / f"{key}.mkv"
        if cpath.exists() and cpath.stat().st_size > 0:
            reused += 1
            # runtime info that overlays need is recomputed cheaply
            for e in seg.get("effects") or []:
                if e["id"] == "phone_mockup":
                    from .effects.panels import _media_assets
                    seg["_runtime"]["phone_simulated"] = not _media_assets(
                        FX.ClipCtx(0, 0, S, 0, 0, 0, fps, it, seg, st, "", work, cache, assets_meta, ""))
                if e["id"] == "cover_story" and mask and it["first"]:
                    seg["_runtime"]["cover_behind"] = True
            report.append({"seg": seg["id"], "effect": "cache", "status": "reused", "msg": f"ใช้คลิปจาก cache ({key[:8]})"})
        else:
            tmp = cache / "clips" / f"{key}.part.mkv"
            render_clip(it, seg, plan, work, tmp, fps, S, assets_meta, bg_png, cache, report,
                        crf=prof["crf"] if not preview else 28, preset="ultrafast" if preview else "veryfast",
                        mask=mask)
            tmp.replace(cpath)
        clip_paths.append(cpath)
        progress(0.05 + 0.65 * (k + 1) / len(items), f"ประกอบคลิป {k + 1}/{len(items)}")
    if reused:
        log(f"ใช้คลิปซ้ำจาก cache {reused}/{len(items)} คลิป")
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in clip_paths))
    base = work / "base.mkv"
    media.ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", base)
    if cancel():
        raise Cancelled("ผู้ใช้ยกเลิกงาน")

    # graphics + subtitles
    feats = features(plan, list(assets_meta.values()))
    sc = build_ass(plan, items, total, assets_meta, feats, report)
    ass_path = work / "graphics.ass"
    ass_path.write_text(sc.document(), encoding="utf-8")

    # audio beds
    sr = 48000
    sfx_track = np.zeros(int((total + 2) * sr), np.float32)
    if st.get("sfx", True):
        bank = {k: synth_sfx(k, sr) for k in SFX_FILES}
        gains = {"whoosh": 0.22, "pop": 0.20, "hit": 0.30}
        first_item = {}
        for it in items:
            first_item.setdefault(it["seg"], it)
        for sid, it in first_item.items():
            kind = segs[sid].get("sfx", "none")
            if kind in bank:
                at = max(0.0, it["out"] - (0.2 if kind == "whoosh" else 0.0))
                x = bank[kind] * gains[kind]
                i0 = int(at * sr)
                sfx_track[i0:i0 + len(x)] += x[: len(sfx_track) - i0]
    media.save_wav(work / "sfx.wav", sfx_track[: int(total * sr) + 1], sr)
    music_mode = st.get("music", "generated")
    music_in = []
    if music_mode == "upload" and assets_meta.get("__music__"):
        music_in = ["-stream_loop", "-1", "-i", assets_meta["__music__"]["path"]]
    elif music_mode == "generated":
        media.save_wav(work / "music.wav", synth_music(total), sr)
        music_in = ["-i", str(work / "music.wav")]

    progress(0.75, "ซับไตเติล กราฟิก และมิกซ์เสียง")
    fonts_rel = os.path.relpath(FONTS_DIR, work)
    vf = f"[0:v]ass=graphics.ass:fontsdir={fonts_rel}[v]"
    voice = "[0:a]aformat=channel_layouts=mono,highpass=f=70"
    if st.get("denoise", True):
        voice += ",afftdn=nr=10:nf=-42"
    voice += ",acompressor=threshold=-22dB:ratio=3:attack=5:release=120:makeup=2,loudnorm=I=-16:TP=-2:LRA=9,aresample=48000"
    fc = vf + ";" + voice + "[vo0]"
    mix = "[vo0]asplit=2[vo][key];"
    parts = ["[vo]"]
    if music_in:
        mdb = float(st.get("music_db", -26))
        fc += f";[2:a]aformat=channel_layouts=mono,aresample=48000,atrim=duration={total:.3f},volume={mdb + 16}dB[mus]"
        mix += "[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=450:makeup=1[duck];"
        parts.append("[duck]")
    else:
        mix += "[key]anullsink;"
    fc += ";" + mix + f"[1:a]aformat=channel_layouts=mono,volume=1.0[sfx];"
    parts.append("[sfx]")
    fc += "".join(parts) + f"amix=inputs={len(parts)}:normalize=0:duration=first,alimiter=limit=0.89:level=false," \
                           f"aformat=sample_rates=48000:channel_layouts=stereo[a]"
    out = job_dir / f"{name}.mp4"
    tmp = job_dir / f"{name}.tmp.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", "base.mkv", "-i", "sfx.wav",
           *music_in, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-preset", prof["preset"], "-crf", str(prof["crf"]),
           "-r", f"{fps:g}", "-c:a", "aac", "-b:a", prof["ab"], "-ar", "48000",
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(tmp.resolve())]
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if p.returncode != 0:
        raise media.ToolError("ffmpeg (final mix) failed:\n" + "\n".join(p.stderr.strip().splitlines()[-15:]))
    tmp.replace(out)
    progress(0.95, "เสร็จสิ้นการเรนเดอร์")
    for s in plan["segments"]:
        s.pop("_runtime", None)
    return {"path": str(out), "items": items, "duration": total, "fps": fps, "boxes": sc.boxes,
            "size": [int(W * S) // 2 * 2, int(H * S) // 2 * 2], "effects_report": report, "reused_clips": reused,
            "profile": "preview" if preview else (profile or st.get("export_profile") or "1080p_high")}
