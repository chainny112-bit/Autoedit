"""AutoEdit web app.  Run:  python app.py  (then open http://localhost:8000)"""
import json
import os

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from engine import ROOT, jobs, pipeline, planner, presets, projects
from engine.effects import TRANSITIONS, capabilities as fx_caps, catalog
from engine.effects.selector import DENSITY, GENRES, MODES
from engine.env import capabilities
from engine.graphics import SUBTITLE_FONTS
from engine.pipeline import load_json
from engine.render import PROFILES

app = FastAPI(title="AutoEdit")
ACTIVE = jobs.ACTIVE


@app.on_event("startup")
def _start():
    jobs.start_worker()
    # work interrupted by a restart is marked so the UI doesn't spin forever (clip cache lets it resume)
    for j in jobs.list_jobs():
        if j["status"] in ACTIVE:
            jobs.patch(j["id"], status="error", message="งานถูกขัดจังหวะ (เซิร์ฟเวอร์รีสตาร์ท) — กดวิเคราะห์ใหม่ได้")
        for vid, v in j["variants"].items():
            if v["status"] in ACTIVE:
                jobs.patch_variant(j["id"], vid, status="cancelled",
                                   message="ถูกขัดจังหวะ (เซิร์ฟเวอร์รีสตาร์ท) — กดเรนเดอร์อีกครั้งเพื่อทำต่อจาก cache")


def _job(jid):
    try:
        return jobs.get(jid)
    except KeyError:
        raise HTTPException(404, "ไม่พบงานนี้")


def _variant(jid, vid):
    j = _job(jid)
    if vid not in j["variants"]:
        raise HTTPException(404, "ไม่พบเวอร์ชันนี้")
    return j, j["variants"][vid]


def _busy(j, vid=None):
    if j["status"] in ACTIVE:
        return True
    return vid is not None and j["variants"][vid]["status"] in ACTIVE


# ---------------------------------------------------------------- environment & catalogues
@app.get("/api/env")
def env():
    caps = fx_caps()
    return {"capabilities": capabilities(), "effect_caps": caps, "effects": catalog(caps),
            "defaults": planner.DEFAULT_SETTINGS,
            "modes": {k: {"name": v["name"], "desc": v["desc"]} for k, v in MODES.items()},
            "densities": {k: {"name": v["name"], "desc": v["desc"]} for k, v in DENSITY.items()},
            "genres": {k: v["name"] for k, v in GENRES.items()},
            "profiles": {k: v["label"] for k, v in PROFILES.items() if k != "preview"},
            "fonts": SUBTITLE_FONTS, "transitions": TRANSITIONS, "aspects": presets.SUPPORTED_ASPECTS,
            "variations": {k: {"name": v["name"], "why": v["why"]} for k, v in jobs.VARIATIONS.items()},
            "options": {"layouts": planner.LAYOUTS, "zooms": planner.ZOOMS, "broll": planner.BROLL_KINDS,
                        "sfx": planner.SFX}}


@app.get("/api/effects")
def effects():
    return catalog()


# ---------------------------------------------------------------- presets
@app.get("/api/presets")
def list_presets():
    return presets.list_all()


def _preset_call(fn, *a):
    try:
        return fn(*a)
    except presets.PresetError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, "ไม่พบ Preset")


@app.post("/api/presets")
def create_preset(data: dict = Body(...)):
    return _preset_call(presets.create, data)


@app.put("/api/presets/{pid}")
def update_preset(pid: str, data: dict = Body(...)):
    return _preset_call(presets.update, pid, data)


@app.post("/api/presets/{pid}/duplicate")
def duplicate_preset(pid: str, data: dict = Body(default={})):
    return _preset_call(presets.duplicate, pid, data.get("name"))


@app.post("/api/presets/{pid}/rename")
def rename_preset(pid: str, data: dict = Body(...)):
    return _preset_call(presets.rename, pid, data.get("name", ""))


@app.delete("/api/presets/{pid}")
def delete_preset(pid: str):
    _preset_call(presets.delete, pid)
    return {"deleted": pid}


# ---------------------------------------------------------------- projects (creative memory)
@app.get("/api/projects")
def list_projects():
    return projects.list_all()


@app.post("/api/projects")
def create_project(data: dict = Body(...)):
    try:
        return projects.create(data.get("name", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/projects/{pid}")
def rename_project(pid: str, data: dict = Body(...)):
    try:
        return projects.rename(pid, data.get("name", ""))
    except KeyError:
        raise HTTPException(404, "ไม่พบโปรเจกต์")


@app.put("/api/projects/{pid}/memory")
def project_memory(pid: str, data: dict = Body(...)):
    try:
        return projects.remember(pid, data.get("preset_id"), data.get("overrides"), data.get("brand"))
    except KeyError:
        raise HTTPException(404, "ไม่พบโปรเจกต์")


# ---------------------------------------------------------------- jobs
@app.get("/api/jobs")
def list_jobs(project: str = None):
    return jobs.list_jobs(project)


@app.post("/api/jobs")
async def create_job(video: UploadFile = File(...), settings: str = Form("{}"), project_id: str = Form("default"),
                     preset_id: str = Form("redrabbit_signature"),
                     transcript: UploadFile | None = File(None), music: UploadFile | None = File(None),
                     references: list[UploadFile] = File(default=[]), broll: list[UploadFile] = File(default=[]),
                     broll_source: str = Form("user"), start: str = Form("auto")):
    caps = capabilities()
    if not caps["ready"]:
        missing = [k for k, v in caps.items() if isinstance(v, dict) and v.get("required") and not v["ok"]]
        raise HTTPException(503, "เครื่องมือที่จำเป็นไม่ครบ: " + ", ".join(missing))
    try:
        user = json.loads(settings or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "settings ไม่ใช่ JSON ที่ถูกต้อง")
    pre = presets.get(preset_id)
    if not pre:
        raise HTTPException(400, "ไม่พบ Preset ที่เลือก")
    proj = projects.get(project_id) or projects.get("default")
    st = {**planner.DEFAULT_SETTINGS, **presets.to_settings(pre, proj["memory"].get("brand")), **user}
    for k in ("accent", "accent2"):   # colour pickers send lowercase; store one canonical form
        if isinstance(st.get(k), str):
            st[k] = st[k].upper()
    try:
        presets.validate({**pre, **{k: v for k, v in st.items() if k in presets.PresetModel.model_fields}})
    except presets.PresetError as e:
        raise HTTPException(400, f"ค่าตั้งค่าไม่ถูกต้อง: {e}")
    try:
        job = jobs.create(video.filename or "video.mp4", video.file, st, proj["id"], preset_id)
        jid = job["id"]
        if transcript and transcript.filename:
            jobs.add_asset(jid, transcript.filename, transcript.file, "transcript")
        if music and music.filename:
            jobs.add_asset(jid, music.filename, music.file, "music")
        for f in references:
            if f.filename:
                jobs.add_asset(jid, f.filename, f.file, "reference")
        for f in broll:
            if f.filename:
                src = broll_source if broll_source in ("user", "stock", "ai") else "user"
                jobs.add_asset(jid, f.filename, f.file, "broll", source=src)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # creative memory: remember this project's choices for next time
    projects.remember(proj["id"], preset_id, {k: v for k, v in user.items()},
                      {"accent": st.get("accent"), "accent2": st.get("accent2"), "brand_name": user.get("brand_name")})
    if not caps["speech_to_text"]["ok"] and not any(a["role"] == "transcript" for a in jobs.get(jid)["assets"]):
        jobs.patch(jid, status="error", message="ไม่มีระบบ Speech-to-Text — ติดตั้ง faster-whisper หรือแนบไฟล์ .srt/.vtt")
        return jobs.get(jid)
    if start in ("auto", "analyze"):
        jobs.enqueue(jid, start)
    return jobs.get(jid)


@app.post("/api/jobs/{jid}/assets")
async def add_assets(jid: str, files: list[UploadFile] = File(...), role: str = Form("broll"), source: str = Form("user")):
    _job(jid)
    out = []
    try:
        for f in files:
            out.append(jobs.add_asset(jid, f.filename, f.file, role, source=source))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return out


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    return _job(jid)


@app.post("/api/jobs/{jid}/analyze")
def analyze(jid: str):
    j = _job(jid)
    if _busy(j) or any(v["status"] in ACTIVE for v in j["variants"].values()):
        raise HTTPException(409, "งานกำลังประมวลผลอยู่")
    jobs.enqueue(jid, "analyze")
    return jobs.get(jid)


# ---------------------------------------------------------------- variants
@app.post("/api/jobs/{jid}/variations")
def variations(jid: str, data: dict = Body(...)):
    j = _job(jid)
    if not (jobs.job_dir(jid) / "analysis.json").exists():
        raise HTTPException(400, "ต้องวิเคราะห์วิดีโอให้เสร็จก่อน")
    kinds = data.get("kinds") or []
    if not kinds:
        raise HTTPException(400, "เลือกอย่างน้อย 1 เวอร์ชัน")
    try:
        ids = jobs.add_variations(jid, kinds)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for v in [x for x in ids if x != "creative"] + [x for x in ids if x == "creative"]:   # creative plans last
        jobs.enqueue(jid, "plan", v)
    if data.get("render") in ("preview", "render"):
        for v in [x for x in ids if x != "creative"] + [x for x in ids if x == "creative"]:
            jobs._q.put((jid, data["render"], v))   # queued after its plan; statuses update as each runs
    return jobs.get(jid)


@app.get("/api/jobs/{jid}/variants/{vid}/plan")
def get_plan(jid: str, vid: str):
    _variant(jid, vid)
    p = load_json(pipeline.variant_dir(jobs.job_dir(jid), vid) / "plan.json")
    if not p:
        raise HTTPException(404, "ยังไม่มี Editing Plan")
    return p


@app.put("/api/jobs/{jid}/variants/{vid}/plan")
def put_plan(jid: str, vid: str, plan: dict = Body(...)):
    j, v = _variant(jid, vid)
    if _busy(j, vid):
        raise HTTPException(409, "งานกำลังประมวลผลอยู่ — รอให้เสร็จก่อนแก้แผน")
    try:
        p = pipeline.update_plan(jobs.job_dir(jid), vid, plan)
    except Exception as e:
        raise HTTPException(400, f"บันทึกแผนไม่สำเร็จ: {e}")
    with jobs._lock:
        jj = jobs.get(jid)
        for o in jj["variants"][vid].get("outputs", {}).values():
            o["stale"] = True
        jj["variants"][vid]["stats"] = pipeline.plan_stats(p)
        jobs.put(jid, jj)
    return p


@app.post("/api/jobs/{jid}/variants/{vid}/restyle")
def restyle(jid: str, vid: str, data: dict = Body(...)):
    """Switch preset / mode / density / intensity without re-analysing the video."""
    j, v = _variant(jid, vid)
    if _busy(j, vid):
        raise HTTPException(409, "งานกำลังประมวลผลอยู่")
    if data.get("preset_id") and not presets.get(data["preset_id"]):
        raise HTTPException(400, "ไม่พบ Preset")
    with jobs._lock:
        jj = jobs.get(jid)
        vv = jj["variants"][vid]
        if "preset_id" in data:
            vv["preset_id"] = data["preset_id"]
            vv["overrides"] = {}
        vv["overrides"].update({k: (data[k].upper() if k.startswith("accent") else data[k])
                                for k in ("mode", "density", "intensity", "subtitle_mode", "subtitle_font",
                                          "export_profile", "accent", "accent2") if k in data})
        jobs.put(jid, jj)
    if jj["project"]:
        projects.remember(jj["project"], data.get("preset_id"), None)
    jobs.enqueue(jid, "plan", vid)
    return jobs.get(jid)


@app.post("/api/jobs/{jid}/variants/{vid}/{action}")
def variant_action(jid: str, vid: str, action: str, data: dict = Body(default={})):
    j, v = _variant(jid, vid)
    if action == "cancel":
        jobs.cancel(jid, vid)
        return jobs.get(jid)
    if action not in ("preview", "render", "plan"):
        raise HTTPException(404)
    if _busy(j, vid):
        raise HTTPException(409, "งานกำลังประมวลผลอยู่")
    if action in ("preview", "render"):
        if not (pipeline.variant_dir(jobs.job_dir(jid), vid) / "plan.json").exists():
            raise HTTPException(400, "ยังไม่มี Editing Plan — วิเคราะห์ก่อน")
        pf = pipeline.preflight(jobs.job_dir(jid), j, vid, "preview" if action == "preview" else "final")
        if pf["errors"]:
            raise HTTPException(400, " / ".join(pf["errors"]))
    jobs.enqueue(jid, action, vid)
    return jobs.get(jid)


@app.get("/api/jobs/{jid}/variants/{vid}/preflight")
def preflight(jid: str, vid: str, kind: str = "preview"):
    j, v = _variant(jid, vid)
    return pipeline.preflight(jobs.job_dir(jid), j, vid, "preview" if kind == "preview" else "final")


@app.delete("/api/jobs/{jid}/variants/{vid}")
def delete_variant(jid: str, vid: str):
    j, v = _variant(jid, vid)
    if vid == "main":
        raise HTTPException(400, "ลบเวอร์ชันหลักไม่ได้")
    if _busy(j, vid):
        raise HTTPException(409, "งานกำลังประมวลผลอยู่")
    import shutil
    shutil.rmtree(pipeline.variant_dir(jobs.job_dir(jid), vid), ignore_errors=True)
    with jobs._lock:
        jj = jobs.get(jid)
        jj["variants"].pop(vid, None)
        jobs.put(jid, jj)
    return jobs.get(jid)


@app.get("/api/jobs/{jid}/compare")
def compare(jid: str):
    """Side-by-side data for the comparison dashboard, incl. where each sentence lands in every version."""
    j = _job(jid)
    out = []
    for vid, v in j["variants"].items():
        vdir = pipeline.variant_dir(jobs.job_dir(jid), vid)
        plan = load_json(vdir / "plan.json")
        qc = load_json(vdir / "qc_final.json") or load_json(vdir / "qc_preview.json")
        seg_at = {}
        if qc:
            for it in qc["timeline"]:
                if it["ci"] == 0:
                    seg_at[it["seg"]] = it["out"]
        out.append({"id": vid, "name": v["name"], "status": v["status"], "message": v.get("message"),
                    "progress": v.get("progress"), "preset": (plan or {}).get("settings", {}).get("preset_name"),
                    "why": v.get("why"), "stats": pipeline.plan_stats(plan) if plan else None,
                    "outputs": v.get("outputs", {}), "seg_at": seg_at,
                    "qc_errors": sum(1 for i in (qc or {}).get("issues", []) if i["level"] == "error") if qc else None})
    segs = []
    an = load_json(jobs.job_dir(jid) / "analysis.json")
    if an:
        segs = [{"id": s["id"], "text": s["text"], "start": s["start"]} for s in an["segments_raw"]]
    return {"variants": out, "segments": segs}


@app.get("/api/jobs/{jid}/files/{name:path}")
def job_file(jid: str, name: str, download: int = 0):
    j = _job(jid)
    d = jobs.job_dir(jid).resolve()
    p = (d / name).resolve()
    ok_dirs = {d, d / "thumbs", d / "assets"}
    in_variant = p.parent.parent == d / "variants"
    allowed = (p.parent in ok_dirs or in_variant) and p.suffix.lower() in {
        ".mp4", ".jpg", ".jpeg", ".png", ".webp", ".json", ".mov", ".m4v", ".webm"}
    if not allowed or not p.exists():
        raise HTTPException(404)
    if download and p.suffix == ".mp4":
        vid = p.parent.name if in_variant else "main"
        return FileResponse(p, filename=f"{j['title']}_{vid}_autoedit.mp4")
    return FileResponse(p)


app.mount("/fonts", StaticFiles(directory=ROOT / "assets" / "fonts"), name="fonts")
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
