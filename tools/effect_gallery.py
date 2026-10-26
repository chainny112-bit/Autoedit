"""Render every effect of the library on real footage (one short clip per effect) and join them into a
labelled gallery video. This is how each effect's rendering function is verified end to end.

Usage: python3 tools/effect_gallery.py VIDEO SRT OUT.mp4 [--preview] [--only id,id]
"""
import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import analyze as A, media, planner, render, transcribe as T, vision   # noqa: E402
from engine import effects as FX   # noqa: E402
from engine.effects import segmentation as SEG   # noqa: E402

# effect -> which sentence of the sample clip shows it best (role/content), and layout it needs
PICK = {"orbit": ("story", "s0"), "couch_wall": ("story", "s5"), "ui_world": ("business", "s4"),
        "frame_break": ("story", "s0"), "digital_zoom": ("story", "s5"), "phone_mockup": ("business", "s4"),
        "checklist": ("business", "s3"), "headline_wall": ("story", "s3"), "zoom_through": ("story", "s6"),
        "chart_grow": ("business", "s1"), "pull_back": ("story", "s0"), "green_screen": ("story", "s6"),
        "paper_cut": ("story", "s3"), "doodle_boil": ("story", "s5"), "vertigo": ("story", "s8"),
        "cover_story": ("story", "s0"), "glassy_type": ("business", "s5")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("srt"); ap.add_argument("out")
    ap.add_argument("--preview", action="store_true"); ap.add_argument("--only", default="")
    ap.add_argument("--work", default="data/gallery")
    a = ap.parse_args()
    work = Path(a.work); work.mkdir(parents=True, exist_ok=True)
    sample_dir = Path(a.video).parent
    clips = {"story": (a.video, a.srt),
             "business": (str(sample_dir / "business_sample_talking_head.mp4"), str(sample_dir / "business_sample.srt"))}
    assets = []
    for f in sample_dir.glob("*.jpg"):
        assets.append({"name": f.name, "path": str(f.resolve()), "kind": "image", "role": "broll", "source": "user",
                       "tags": []})
    bases = {}
    for name, (video, srt) in clips.items():
        info = media.probe(video)
        wav = work / f"{name}.wav"
        media.extract_audio(video, wav)
        sil, _ = media.detect_silences(wav)
        segs = T.segments_from_subtitles(srt, T.speech_mask_from_silences(sil, info["duration"]))
        A.classify_cuts(segs, {}, log=lambda *_: None)
        vis = vision.analyze(video, info, log=lambda *_: None)
        info["_silences"] = sil
        base = planner.build_plan(dict(info), copy.deepcopy(segs), vis, {"title_cards": False}, [], {},
                                  log=lambda *_: None)
        base["source"]["path"] = str(Path(video).resolve())
        bases[name] = base
    meta = {x["name"]: x for x in assets}
    only = [x for x in a.only.split(",") if x]
    results, parts = [], []
    for n, eid in enumerate(FX._ORDER, 1):
        if only and eid not in only:
            continue
        eff = FX.REGISTRY[eid]
        clip, sid = PICK[eid]
        plan = copy.deepcopy(bases[clip])
        for s in plan["segments"]:
            s["keep"] = s["keep"] and (s["id"] == sid or (eid == "zoom_through" and s["id"] == "s5"))
            if not s["keep"]:
                s["clips"] = []
        seg = next(s for s in plan["segments"] if s["id"] == sid)
        seg["effects"] = [] if eid == "zoom_through" else [{"id": eid, "params": eff.default_params("high")}]
        if eid == "zoom_through":
            seg["transition_in"] = {"id": "zoom_through", "params": eff.default_params("high")}
        seg["layout"] = "pip" if eff.category == "panel" else "full"
        if eff.category != "panel":
            seg["broll"] = {"kind": "none"}
        if eid in ("green_screen", "couch_wall") and assets:
            seg["_fx_asset"] = assets[0]["name"]
        if eid == "paper_cut":
            seg.pop("_fx_asset", None)
        seg["title"] = {"cover_story": "คนหายไปทั้งหมู่บ้าน", "glassy_type": "ทำทีละขั้น"}.get(eid, "")
        seg["zoom"] = "none"
        plan["settings"]["music"] = "none"
        plan["settings"]["sfx"] = False
        vdir = work / eid
        if vdir.exists():
            shutil.rmtree(vdir)
        vdir.mkdir()
        t = time.time()
        try:
            res = render.render(vdir, plan, meta, preview=a.preview, log=lambda *_: None, cache_dir=work / "cache")
            rep = [r for r in res["effects_report"] if r["effect"] in (eid, "segmentation")]
            status = "fallback" if any(r["status"] == "fallback" for r in rep) else "ok"
            results.append({"n": n, "id": eid, "status": status, "seconds": round(time.time() - t, 1),
                            "report": rep, "file": res["path"]})
            parts.append((n, eff, res["path"]))
            print(f"{n:02d} {eid:14s} {status:8s} {time.time() - t:5.1f}s  " + "; ".join(r["msg"] for r in rep)[:150],
                  flush=True)
        except Exception as e:
            results.append({"n": n, "id": eid, "status": "error", "error": str(e)[-800:]})
            print(f"{n:02d} {eid:14s} ERROR {str(e)[-600:]}", flush=True)
    (work / "gallery_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    if not parts:
        return
    # label each part and join
    from engine import graphics as G
    labelled = []
    for n, eff, path in parts:
        sc = G.Script({"accent": "#BC0000", "accent2": "#A8CE20"})
        dur = media.probe(path)["duration"]
        sc.shape(0, dur, 40, 60, G.rrect(1000, 150, 26), fill="#000000", fill_a=0x40, border="#BC0000", bord=3, layer=50)
        sc.text(0, dur, 540, 112, f"EFFECT {n:02d} — {eff.name.upper()}", size=54, color="#FFFFFF", bord=0, shad=0,
                layer=51)
        tag = {"real": "ทำงานจริง", "simulation": "จำลอง (Simulation)", "needs_api": "ต้องใช้ API"}[eff.implementation]
        sc.text(0, dur, 540, 168, f"{eff.name_th} · {tag}", size=34, family="Kanit SemiBold", color="#A8CE20", bord=0,
                shad=0, layer=51)
        ap_ = work / f"label_{eff.id}.ass"
        ap_.write_text(sc.document(), encoding="utf-8")
        lp = work / f"labelled_{n:02d}.mp4"
        import os
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(Path(path).resolve()), "-vf",
                        f"ass={ap_.name}:fontsdir={os.path.relpath(Path(__file__).resolve().parent.parent / 'assets/fonts', work)}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "128k",
                        "-ar", "48000", "-ac", "2", str(lp.resolve())], check=True, cwd=work)
        labelled.append(lp)
    lst = work / "gallery.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in labelled))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", a.out], check=True)
    print("gallery:", a.out)


if __name__ == "__main__":
    main()
