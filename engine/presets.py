"""Style presets: 7 built-ins + user presets stored as validated JSON (data/presets.json)."""
import json
import re
import threading
import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from . import DATA_DIR
from .effects import REGISTRY, TRANSITIONS
from .graphics import SUBTITLE_FONTS
from .render import PROFILES

STORE = DATA_DIR / "presets.json"
_lock = threading.RLock()
SUPPORTED_ASPECTS = ["9:16"]     # the renderer's layouts are built for vertical video only (see README)
EXPORT_PROFILES = [k for k in PROFILES if k != "preview"]


class PresetModel(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=400)
    accent: Optional[str] = None           # None = use the project's brand colours
    accent2: Optional[str] = None
    subtitle_font: str = "Kanit ExtraBold"
    subtitle_mode: Literal["keyword", "karaoke"] = "keyword"
    subtitle_size: int = Field(default=92, ge=60, le=130)
    intensity: Literal["low", "medium", "high"] = "medium"
    density: int = Field(default=2, ge=1, le=4)
    mode: Literal["clean", "story", "retention", "mograph", "experimental", "auto"] = "auto"
    pacing: Literal["calm", "normal", "fast"] = "normal"
    allowed_effects: list[str] = []         # empty = all effects allowed
    banned_effects: list[str] = []
    transitions: list[str] = ["cut", "flash", "zoom_through"]
    sfx: bool = True
    music: Literal["generated", "upload", "none"] = "generated"
    music_db: float = Field(default=-26, ge=-45, le=-12)
    title_cards: bool = True
    broll_density: Literal["low", "normal", "high"] = "normal"
    aspect: str = "9:16"
    export_profile: str = "1080p_high"

    @field_validator("accent", "accent2")
    @classmethod
    def _color(cls, v):
        if v is None or v == "":
            return None
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError("สีต้องอยู่ในรูปแบบ #RRGGBB")
        return v.upper()

    @field_validator("subtitle_font")
    @classmethod
    def _font(cls, v):
        if v not in SUBTITLE_FONTS:
            raise ValueError(f"ฟอนต์ต้องเป็นหนึ่งใน {SUBTITLE_FONTS}")
        return v

    @field_validator("allowed_effects", "banned_effects")
    @classmethod
    def _effects(cls, v):
        bad = [e for e in v if e not in REGISTRY]
        if bad:
            raise ValueError(f"ไม่รู้จักเอฟเฟกต์: {bad}")
        return list(dict.fromkeys(v))

    @field_validator("transitions")
    @classmethod
    def _trans(cls, v):
        bad = [t for t in v if t not in TRANSITIONS]
        if bad:
            raise ValueError(f"ไม่รู้จัก Transition: {bad}")
        return list(dict.fromkeys(v)) or ["cut"]

    @field_validator("aspect")
    @classmethod
    def _aspect(cls, v):
        if v not in SUPPORTED_ASPECTS:
            raise ValueError(f"ขณะนี้รองรับเฉพาะ {SUPPORTED_ASPECTS} (เลย์เอาต์ทั้งหมดออกแบบสำหรับวิดีโอแนวตั้ง)")
        return v

    @field_validator("export_profile")
    @classmethod
    def _profile(cls, v):
        if v not in EXPORT_PROFILES:
            raise ValueError(f"Export profile ต้องเป็นหนึ่งใน {EXPORT_PROFILES}")
        return v


B = lambda **kw: PresetModel(**kw).model_dump()   # noqa: E731 - validated at import time
BUILTIN = {
    "redrabbit_signature": B(
        name="A — RedRabbit Signature", accent="#BC0000", accent2="#A8CE20", mode="retention", density=2,
        description="ดำ ขาว แดงตามแบรนด์ · Dynamic Subtitle เน้นคำ · Punch-in + Jump Cut · Motion Graphics ทันสมัย · ภาพประกอบสัมพันธ์กับบทพูด",
        banned_effects=["vertigo"]),
    "dark_gold_story": B(
        name="B — Dark Gold Story", accent="#FFB000", accent2="#FF7A00", mode="story", density=2,
        description="พื้นดำ ส้มทอง · Headline Wall + Glowing Typography · Phone Mockup + การ์ดภาพประกอบ · Pull-back Reveal และ Digital Zoom ในช่วงสำคัญ",
        allowed_effects=["headline_wall", "phone_mockup", "pull_back", "digital_zoom", "glassy_type", "paper_cut",
                         "zoom_through", "chart_grow", "checklist", "cover_story", "doodle_boil"]),
    "clean_creator": B(
        name="C — Clean Creator", mode="clean", density=1, intensity="low", subtitle_size=88,
        description="ผู้พูดเป็นหลัก ซับขาวเน้นคำพอดี ตัดช่วงเงียบ ซูม/Transition เท่าที่จำเป็น",
        transitions=["cut"], sfx=False, title_cards=False, broll_density="low"),
    "cinematic_storytelling": B(
        name="D — Cinematic Storytelling", mode="story", density=2, pacing="calm",
        description="เน้นภาพประกอบและบรรยากาศ · Pull-back Reveal, Orbit Simulation, Parallax · Sound Design สัมพันธ์กับเรื่อง",
        allowed_effects=["pull_back", "orbit", "paper_cut", "vertigo", "couch_wall", "zoom_through", "digital_zoom",
                         "headline_wall", "glassy_type", "cover_story"]),
    "high_retention_social": B(
        name="E — High-Retention Social", mode="retention", density=3, pacing="fast", intensity="high",
        description="Hook ชัด ตัดกระชับ Dynamic Subtitle + Digital Zoom + B-roll · Transition เฉพาะจุดเปลี่ยนประเด็น",
        transitions=["cut", "zoom_through"]),
    "motion_graphics_pro": B(
        name="F — Motion Graphics Pro", mode="mograph", density=3,
        description="UI World, Chart Grow, Checklist, Glassy Type · แสดงข้อมูลเป็นลำดับ ใช้กราฟิกแทนข้อความยาว",
        allowed_effects=["ui_world", "chart_grow", "checklist", "glassy_type", "headline_wall", "phone_mockup",
                         "digital_zoom", "zoom_through", "doodle_boil"]),
    "creative_experimental": B(
        name="G — Creative Experimental", mode="experimental", density=4, intensity="high",
        description="AI ทดลองผสมเอฟเฟกต์ทั้ง 17 แบบ · Frame Break, Paper Cut, Doodle Boil, Zoom-through เมื่อเหมาะสม โดยรักษาความชัดเจนของเนื้อหา"),
}
for k, v in BUILTIN.items():
    v.update(id=k, builtin=True)


def _read():
    if not STORE.exists():
        return {"presets": {}}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        bad = STORE.with_suffix(f".corrupt-{int(time.time())}.json")
        STORE.replace(bad)
        return {"presets": {}}


def _write(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def list_all():
    with _lock:
        custom = _read()["presets"]
    return list(BUILTIN.values()) + sorted(custom.values(), key=lambda p: p.get("created", 0))


def get(pid):
    if pid in BUILTIN:
        return BUILTIN[pid]
    with _lock:
        return _read()["presets"].get(pid)


class PresetError(ValueError):
    pass


def validate(data):
    try:
        return PresetModel(**{k: v for k, v in data.items() if k in PresetModel.model_fields}).model_dump()
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            ctx = err.get("ctx") or {}
            th = {"less_than_equal": f"ต้องไม่เกิน {ctx.get('le')}", "greater_than_equal": f"ต้องไม่น้อยกว่า {ctx.get('ge')}",
                  "string_too_short": "ห้ามเว้นว่าง", "string_too_long": f"ยาวเกิน {ctx.get('max_length')} ตัวอักษร",
                  "literal_error": f"ต้องเป็นหนึ่งใน {ctx.get('expected')}", "int_parsing": "ต้องเป็นตัวเลขจำนวนเต็ม",
                  "float_parsing": "ต้องเป็นตัวเลข", "bool_parsing": "ต้องเป็น true/false", "list_type": "ต้องเป็นรายการ"}
            msgs.append(f"{loc}: {th.get(err['type'], err['msg'].replace('Value error, ', ''))}")
        raise PresetError("; ".join(msgs))


def _save(pid, preset):
    with _lock:
        data = _read()
        data["presets"][pid] = preset
        _write(data)
        stored = _read()["presets"].get(pid)   # read back: only report success if it is really on disk
    if stored != preset:
        raise PresetError("บันทึกลงไฟล์ไม่สำเร็จ")
    return stored


def create(data):
    p = validate(data)
    pid = "custom_" + uuid.uuid4().hex[:8]
    p.update(id=pid, builtin=False, created=time.time(), updated=time.time())
    return _save(pid, p)


def update(pid, data):
    if pid in BUILTIN:
        raise PresetError("Preset ในตัวแก้ไขไม่ได้ — ใช้ 'ทำสำเนา' แล้วแก้ไขสำเนา")
    cur = get(pid)
    if not cur:
        raise KeyError(pid)
    p = validate({**cur, **data})
    p.update(id=pid, builtin=False, created=cur.get("created", time.time()), updated=time.time())
    return _save(pid, p)


def duplicate(pid, name=None):
    src = get(pid)
    if not src:
        raise KeyError(pid)
    return create({**src, "name": (name or f"{src['name']} (สำเนา)")[:60]})


def rename(pid, name):
    return update(pid, {"name": name})


def delete(pid):
    if pid in BUILTIN:
        raise PresetError("ลบ Preset ในตัวไม่ได้")
    with _lock:
        data = _read()
        if pid not in data["presets"]:
            raise KeyError(pid)
        del data["presets"][pid]
        _write(data)
        if pid in _read()["presets"]:
            raise PresetError("ลบไม่สำเร็จ")
    return True


def to_settings(preset, brand=None):
    """Preset -> render/planner settings. Presets without colours use the project's brand colours."""
    brand = brand or {}
    s = {k: v for k, v in preset.items() if k not in ("id", "builtin", "name", "description", "created", "updated")}
    s["accent"] = preset.get("accent") or brand.get("accent") or "#BC0000"
    s["accent2"] = preset.get("accent2") or brand.get("accent2") or "#A8CE20"
    if brand.get("brand_name"):
        s["brand_name"] = brand["brand_name"]
    s["preset_id"] = preset.get("id")
    s["preset_name"] = preset.get("name")
    return s
