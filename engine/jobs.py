"""Job store, variants and a single background worker (one render at a time keeps FFmpeg from fighting for CPU).
Each job = one source video + one shared analysis + N variants (editing plans/renders)."""
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import DATA_DIR, pipeline, presets, projects, thai
from .pipeline import AUDIO_EXT, IMAGE_EXT, SUB_EXT, VIDEO_EXT, load_json, save_json
from .render import Cancelled

JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.RLock()
_q: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
_cancel = set()
ACTIVE = {"queued", "analyzing", "planning", "previewing", "rendering"}

VARIATIONS = {
    "clean": {"name": "A — CLEAN", "preset_id": "clean_creator", "overrides": {"density": 1},
              "why": "ตัดช่วงเงียบ/คำซ้ำ ซับอ่านง่าย กราฟิกน้อย เน้นความเป็นธรรมชาติ"},
    "cinematic": {"name": "B — CINEMATIC", "preset_id": "cinematic_storytelling", "overrides": {"density": 2},
                  "why": "เน้นภาพประกอบ กล้องจำลอง การเปลี่ยนฉาก และบรรยากาศ"},
    "retention": {"name": "C — HIGH RETENTION", "preset_id": "high_retention_social", "overrides": {"density": 3},
                  "why": "Hook ชัด Dynamic Subtitle + Punch-in สลับภาพประกอบตามบทพูด จังหวะกระชับ"},
    "creative": {"name": "D — CREATIVE", "preset_id": "creative_experimental", "overrides": {"density": 4},
                 "why": "ทดลองเอฟเฟกต์จาก Library ที่ต่างจากเวอร์ชันอื่น แต่ยังดูเป็นมืออาชีพ"},
    "auto": {"name": "E — AUTO DIRECTOR", "preset_id": None, "overrides": {"mode": "auto"},
             "why": "AI เลือกแนวทางจากเนื้อหา"},
}
AUTO_DENSITY = {"news": 3, "exciting": 3, "promo": 3, "howto": 2, "story": 2, "review": 2, "talking": 2}


def job_dir(jid):
    if not re.fullmatch(r"[a-f0-9]{12}", jid or ""):
        raise KeyError(jid)
    d = JOBS_DIR / jid
    if not d.exists():
        raise KeyError(jid)
    return d


def get(jid):
    with _lock:
        return load_json(job_dir(jid) / "job.json")


def put(jid, job):
    with _lock:
        job["updated"] = time.time()
        save_json(job_dir(jid) / "job.json", job)


def patch(jid, **kw):
    with _lock:
        j = get(jid)
        j.update(kw)
        put(jid, j)
        return j


def patch_variant(jid, vid, **kw):
    with _lock:
        j = get(jid)
        j["variants"][vid].update(kw)
        put(jid, j)
        return j


def log(jid, msg, vid=None):
    with _lock:
        j = get(jid)
        line = time.strftime("%H:%M:%S ") + (f"[{vid}] " if vid else "") + str(msg)
        j.setdefault("log", []).append(line)
        j["log"] = j["log"][-500:]
        put(jid, j)
    print(f"[{jid}{'/' + vid if vid else ''}] {msg}", flush=True)


def safe_name(name):
    name = Path(name).name
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^\w฀-๿\-]+", "_", stem).strip("_")[:60] or "file"
    return stem + ext


def classify_file(name, hint=None):
    ext = Path(name).suffix.lower()
    if hint in ("reference", "broll", "music", "transcript"):
        return hint
    if ext in SUB_EXT:
        return "transcript"
    if ext in AUDIO_EXT:
        return "music"
    return "broll"


def _new_variant(name, preset_id=None, overrides=None, kind="custom", why=""):
    return {"name": name, "preset_id": preset_id, "overrides": overrides or {}, "kind": kind, "why": why,
            "status": "new", "progress": 0.0, "message": "", "outputs": {}, "created": time.time(), "error": None}


def create(video_name, video_stream, settings=None, project_id="default", preset_id=None):
    jid = uuid.uuid4().hex[:12]
    d = JOBS_DIR / jid
    (d / "assets").mkdir(parents=True)
    ext = Path(video_name).suffix.lower()
    if ext not in VIDEO_EXT:
        shutil.rmtree(d)
        raise ValueError(f"ไม่รองรับไฟล์ {ext} — ใช้ MP4/MOV/M4V/MKV/WEBM")
    src = d / f"source{ext}"
    with open(src, "wb") as f:
        shutil.copyfileobj(video_stream, f)
    proj = projects.get(project_id) or projects.get("default")
    brand = (proj.get("memory") or {}).get("brand") or {}
    settings = settings or {}
    if preset_id:
        settings["preset_id"] = preset_id
    job = {"id": jid, "title": Path(video_name).stem, "source": src.name, "created": time.time(), "status": "uploaded",
           "progress": 0.0, "message": "", "settings": settings, "assets": [], "log": [], "project": proj["id"],
           "brand": brand, "variants": {"main": _new_variant("หลัก", None, {}, "main")}, "active_variant": "main"}
    save_json(d / "job.json", job)
    return job


def add_asset(jid, name, stream, role_hint=None, source="user", tags=None):
    d = job_dir(jid)
    name = safe_name(name)
    role = classify_file(name, role_hint)
    ext = Path(name).suffix.lower()
    if role in ("broll", "reference") and ext not in IMAGE_EXT | VIDEO_EXT:
        raise ValueError(f"ไฟล์ภาพประกอบ/อ้างอิงต้องเป็นภาพหรือวิดีโอ: {name}")
    if role == "music" and ext not in AUDIO_EXT:
        raise ValueError(f"ไฟล์เพลงต้องเป็นไฟล์เสียง: {name}")
    if role == "transcript" and ext not in SUB_EXT:
        raise ValueError(f"ไฟล์ Transcript ต้องเป็น .srt หรือ .vtt: {name}")
    path = d / "assets" / name
    with open(path, "wb") as f:
        shutil.copyfileobj(stream, f)
    kind = "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else "audio" if ext in AUDIO_EXT else "text"
    auto_tags = [t for t in thai.tokenize(Path(name).stem.replace("_", " ").replace("-", " ")) if t != " "]
    asset = {"name": name, "path": str(path.resolve()), "kind": kind, "role": role, "source": source,
             "tags": list(dict.fromkeys((tags or []) + auto_tags))}
    with _lock:
        j = get(jid)
        j["assets"] = [a for a in j.get("assets", []) if a["name"] != name] + [asset]
        put(jid, j)
    return asset


def list_jobs(project=None):
    out = []
    for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        j = load_json(d / "job.json")
        if j and (project is None or j.get("project") == project):
            out.append({k: j.get(k) for k in ("id", "title", "status", "progress", "message", "created", "project")} |
                       {"variants": {v: {"name": x["name"], "status": x["status"], "outputs": x.get("outputs", {})}
                                     for v, x in j.get("variants", {}).items()}})
    return out


def add_variations(jid, kinds):
    """Create variant entries (shared analysis) and return their ids."""
    an = load_json(job_dir(jid) / "analysis.json")
    genre = None
    if an:
        from .effects.selector import detect_genre
        tmp = [dict(s, keep=True) for s in an["segments_raw"]]
        genre = detect_genre(tmp)
    ids = []
    with _lock:
        j = get(jid)
        for k in kinds:
            if k not in VARIATIONS:
                raise ValueError(f"ไม่รู้จักเวอร์ชัน {k}")
            spec = VARIATIONS[k]
            ov = dict(spec["overrides"])
            why = spec["why"]
            if k == "auto" and genre:
                ov["density"] = AUTO_DENSITY.get(genre["genre"], 2)
                why = f"{genre['reason']} → เลือกความหนาแน่นระดับ {ov['density']} และให้ AI ผสมเอฟเฟกต์ตามเนื้อหา"
            j["variants"][k] = _new_variant(spec["name"], spec["preset_id"], ov, k, why)
            ids.append(k)
        put(jid, j)
    return ids


def enqueue(jid, action, vid="main"):
    if action in ("analyze", "auto"):
        patch(jid, status="queued", message="รอคิววิเคราะห์", progress=0.0, error=None)
    else:
        patch_variant(jid, vid, status="queued", message="รอคิว", progress=0.0, error=None)
    _cancel.discard((jid, vid))
    _q.put((jid, action, vid))


def cancel(jid, vid):
    _cancel.add((jid, vid))
    j = get(jid)
    v = j["variants"].get(vid)
    if v and v["status"] == "queued":
        patch_variant(jid, vid, status="cancelled", message="ยกเลิกแล้ว (ยังไม่ได้เริ่ม)")
    return True


def run(jid, action, vid="main"):
    d = job_dir(jid)

    def prog(p, m=""):
        patch_variant(jid, vid, progress=round(float(p), 3), message=m)

    def aprog(p, m=""):
        patch(jid, progress=round(float(p), 3), message=m)

    lg = lambda m: log(jid, m, vid)
    is_cancelled = lambda: (jid, vid) in _cancel
    if is_cancelled() and action not in ("analyze",):
        patch_variant(jid, vid, status="cancelled", message="ยกเลิกแล้ว")
        _cancel.discard((jid, vid))
        return
    try:
        if action in ("analyze", "auto"):
            patch(jid, status="analyzing", progress=0.0, message="เริ่มวิเคราะห์", error=None)
            pipeline.analyze_job(d, get(jid), log=lambda m: log(jid, m), progress=aprog)
            patch(jid, status="ready", progress=1.0, message="วิเคราะห์เสร็จ")
            for v in list(get(jid)["variants"]):
                _plan(jid, v)
            if action == "auto":
                j = get(jid)
                action = "preview" if j["settings"].get("review_before_export") else "render"
                vid = "main"
                prog = lambda p, m="": patch_variant(jid, "main", progress=round(float(p), 3), message=m)
                lg = lambda m: log(jid, m, "main")
        if action == "plan":
            _plan(jid, vid)
        if action in ("preview", "render"):
            preview = action == "preview"
            patch_variant(jid, vid, status="previewing" if preview else "rendering", progress=0.0,
                          message="สร้าง Preview" if preview else "เรนเดอร์วิดีโอจริง")
            rep = pipeline.render_variant(d, get(jid), vid, preview=preview, log=lg, progress=prog, cancel=is_cancelled)
            j = get(jid)
            key = "preview" if preview else "final"
            v = j["variants"][vid]
            v.setdefault("outputs", {})[key] = {"file": f"variants/{vid}/{key}.mp4", "qc": rep["issues"],
                                                 "duration": rep["duration"], "t": time.time(), "size": rep["size"],
                                                 "fps": rep["fps"], "profile": rep["profile"],
                                                 "seconds": rep["seconds"], "reused_clips": rep["reused_clips"]}
            errs = [i for i in rep["issues"] if i["level"] == "error"]
            v.update(status="preview_ready" if preview else "done", progress=1.0,
                     message=("Preview พร้อม" if preview else "เสร็จสิ้น") +
                     (f" (QC พบข้อผิดพลาด {len(errs)} รายการ)" if errs else " ✓ ผ่าน QC"))
            put(jid, j)
    except Cancelled as e:
        log(jid, str(e), vid)
        patch_variant(jid, vid, status="cancelled", message=str(e))
        _cancel.discard((jid, vid))
    except Exception as e:
        log(jid, "ERROR: " + str(e), vid)
        log(jid, traceback.format_exc()[-1500:], vid)
        if action in ("analyze", "auto") and get(jid)["status"] in ("analyzing", "queued"):
            patch(jid, status="error", error=str(e), message=str(e)[:300])
        else:
            patch_variant(jid, vid, status="error", error=str(e), message=str(e)[:300])


def _plan(jid, vid):
    patch_variant(jid, vid, status="planning", message="สร้าง Editing Plan", progress=0.5)
    plan = pipeline.plan_variant(job_dir(jid), get(jid), vid, log=lambda m: log(jid, m, vid))
    stats = pipeline.plan_stats(plan)
    with _lock:   # files rendered from the previous plan no longer match it
        j = get(jid)
        for o in j["variants"][vid].get("outputs", {}).values():
            o["stale"] = True
        put(jid, j)
    patch_variant(jid, vid, status="plan_ready", message="Editing Plan พร้อม", progress=1.0, stats=stats,
                  direction=plan.get("direction"), planned_at=time.time())


def plan_creative_avoid(jid):
    """Creative variant should look different: avoid effects the other variants already use."""
    j = get(jid)
    used = set()
    for v, x in j["variants"].items():
        if v != "creative":
            used |= set((x.get("stats") or {}).get("effect_counts", {}).keys())
    if "creative" in j["variants"]:
        j["variants"]["creative"]["overrides"]["avoid_effects"] = sorted(used)
        put(jid, j)


def _worker():
    while True:
        jid, action, vid = _q.get()
        try:
            if action == "plan" and vid == "creative":
                plan_creative_avoid(jid)
            run(jid, action, vid)
        finally:
            _q.task_done()


_started = False


def start_worker():
    global _started
    if not _started:
        threading.Thread(target=_worker, daemon=True).start()
        _started = True
