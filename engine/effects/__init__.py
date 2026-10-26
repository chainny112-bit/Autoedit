"""Effect registry (17 effects). Add an effect by implementing it in a module and listing it in build()."""
from . import camera, compositing, overlays, panels, segmentation
from .base import ClipCtx, Effect, INTENSITY, Param

_ORDER = ["orbit", "couch_wall", "ui_world", "frame_break", "digital_zoom", "phone_mockup", "checklist",
          "headline_wall", "zoom_through", "chart_grow", "pull_back", "green_screen", "paper_cut", "doodle_boil",
          "vertigo", "cover_story", "glassy_type"]

REGISTRY = {e.id: e for mod in (camera, compositing, panels, overlays) for e in mod.build()}
assert sorted(REGISTRY) == sorted(_ORDER), sorted(set(REGISTRY) ^ set(_ORDER))
TRANSITIONS = ["cut", "flash", "zoom_through"]


def get(eid):
    return REGISTRY.get(eid)


def capabilities():
    import os
    seg_ok, seg_why = segmentation.status()
    return {"segmentation": seg_ok, "segmentation_detail": seg_why, "chroma": False,
            "ai_image": bool(os.environ.get("AUTOEDIT_IMAGE_CMD"))}


def catalog(caps=None):
    caps = caps or capabilities()
    out = []
    for n, eid in enumerate(_ORDER, 1):
        d = REGISTRY[eid].describe(caps)
        d["number"] = n
        enh = [r for r in d["enhanced_by"] if not caps.get(r)]
        d["degraded"] = bool(enh)
        d["degraded_reason"] = ("ทำงานแบบ fallback เพราะไม่มี: " + ", ".join(enh)) if enh else ""
        out.append(d)
    return out
