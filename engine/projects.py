"""Projects keep separate creative memory (last preset, density, subtitle, export profile, brand style) so one
client's style never leaks into another project."""
import json
import threading
import time
import uuid

from . import DATA_DIR

STORE = DATA_DIR / "projects.json"
_lock = threading.RLock()
DEFAULT = {"id": "default", "name": "ทั่วไป", "created": 0,
           "memory": {"preset_id": "redrabbit_signature", "overrides": {},
                      "brand": {"accent": "#BC0000", "accent2": "#A8CE20", "brand_name": "RED RABBIT"}}}
MEMORY_KEYS = {"density", "intensity", "mode", "subtitle_mode", "subtitle_size", "subtitle_font", "export_profile",
               "pacing", "music", "music_db", "sfx", "title_cards", "review_before_export", "use_llm", "allow_ai_images",
               "accent", "accent2", "fps", "denoise", "cut_fillers", "cut_repeats", "asr_model", "vignette"}


def _read():
    if not STORE.exists():
        return {"projects": {"default": DEFAULT}}
    data = json.loads(STORE.read_text(encoding="utf-8"))
    data["projects"].setdefault("default", DEFAULT)
    return data


def _write(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def list_all():
    with _lock:
        return sorted(_read()["projects"].values(), key=lambda p: p.get("created", 0))


def get(pid):
    with _lock:
        return _read()["projects"].get(pid)


def create(name):
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("ต้องตั้งชื่อโปรเจกต์")
    pid = uuid.uuid4().hex[:10]
    with _lock:
        data = _read()
        data["projects"][pid] = {"id": pid, "name": name, "created": time.time(),
                                 "memory": json.loads(json.dumps(DEFAULT["memory"]))}
        _write(data)
        return _read()["projects"][pid]


def rename(pid, name):
    with _lock:
        data = _read()
        if pid not in data["projects"]:
            raise KeyError(pid)
        data["projects"][pid]["name"] = name.strip()[:60]
        _write(data)
        return _read()["projects"][pid]


def remember(pid, preset_id=None, overrides=None, brand=None):
    """Store the user's latest choices for this project."""
    with _lock:
        data = _read()
        if pid not in data["projects"]:
            raise KeyError(pid)
        mem = data["projects"][pid].setdefault("memory", {})
        if preset_id:
            mem["preset_id"] = preset_id
        if overrides is not None:
            mem["overrides"] = {k: v for k, v in overrides.items() if k in MEMORY_KEYS}
        if brand:
            b = mem.setdefault("brand", {})
            b.update({k: v for k, v in brand.items() if k in ("accent", "accent2", "brand_name") and v})
        mem["updated"] = time.time()
        _write(data)
        return _read()["projects"][pid]["memory"]
