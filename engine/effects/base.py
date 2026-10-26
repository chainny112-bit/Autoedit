"""Effect interface. Every effect is a self-contained object registered in the effect registry.

Render hooks (all optional; the renderer calls whichever an effect implements):
  camera(p, cx)            -> ffmpeg filter chain applied to the presenter stream (W x H), clip time t
  composite(p, cx, idx)    -> (input_args, graph) consuming [pres] (+[mask]) producing [v]   (layer compositing)
  panel(p, cx, idx)        -> (input_args, graph) producing [panel]  (content of the top panel / full b-roll)
  post(p, cx)              -> filter chain applied to the finished frame [v] (e.g. glass blur)
  overlay(sc, p, ox)       -> add events to the global ASS motion-graphics script
"""
from dataclasses import dataclass, field

INTENSITY = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Param:
    name: str
    type: str                 # float | int | choice | bool | text
    default: object
    label: str = ""
    min: float = None
    max: float = None
    choices: list = None
    by_intensity: tuple = None   # (low, medium, high) defaults


@dataclass
class Effect:
    id: str
    name: str
    name_th: str
    category: str            # camera | composite | panel | overlay | transition
    implementation: str      # real | simulation | needs_api
    note: str                # honest description of what is actually rendered
    params: list = field(default_factory=list)
    requires: list = field(default_factory=list)        # hard requirements: e.g. ["segmentation"]
    enhanced_by: list = field(default_factory=list)     # optional: better result when available
    inputs: list = field(default_factory=list)          # Thai description of input assets
    fallback: str = ""        # Thai description of the fallback behaviour
    layout: str = None        # layout the segment must use (full / pip / broll_full) or None
    attention: float = 1.0    # how much viewer attention it takes (density budget)
    cost: float = 1.0         # relative processing cost per second

    # --- parameters -------------------------------------------------------
    def default_params(self, intensity="medium"):
        k = INTENSITY.get(intensity, 1)
        out = {}
        for p in self.params:
            out[p.name] = p.by_intensity[k] if p.by_intensity else p.default
        return out

    def clean_params(self, given, intensity="medium"):
        out = self.default_params(intensity)
        for p in self.params:
            if p.name not in (given or {}):
                continue
            v = given[p.name]
            try:
                if p.type == "float":
                    v = float(v)
                    v = min(p.max, max(p.min, v)) if p.min is not None else v
                elif p.type == "int":
                    v = int(v)
                    v = min(p.max, max(p.min, v)) if p.min is not None else v
                elif p.type == "bool":
                    v = v in (True, "true", "1", 1, "on")
                elif p.type == "choice":
                    v = v if v in p.choices else p.default
                else:
                    v = str(v)[:200]
            except (TypeError, ValueError):
                continue
            out[p.name] = v
        return out

    # --- selection ---------------------------------------------------------
    def eligible(self, f, ctx):
        """Return (score 0..1, Thai reason, param overrides) or None if the effect doesn't fit this segment."""
        return None

    def available(self, caps):
        missing = [r for r in self.requires if not caps.get(r)]
        if missing:
            return False, "ต้องใช้ " + ", ".join(missing)
        return True, ""

    def describe(self, caps=None):
        ok, why = self.available(caps or {})
        return {
            "id": self.id, "name": self.name, "name_th": self.name_th, "category": self.category,
            "implementation": self.implementation, "note": self.note, "requires": self.requires,
            "enhanced_by": self.enhanced_by, "inputs": self.inputs, "fallback": self.fallback,
            "layout": self.layout, "available": ok, "unavailable_reason": why,
            "params": [{"name": p.name, "type": p.type, "default": p.default, "label": p.label, "min": p.min,
                        "max": p.max, "choices": p.choices} for p in self.params],
        }


@dataclass
class ClipCtx:
    """What a render hook knows about the clip it is rendering."""
    W: int
    H: int
    S: float
    d: float              # clip duration
    t_off: float          # time from segment start to this clip's start
    seg_dur: float
    fps: float
    item: dict
    seg: dict
    settings: dict
    intensity: str
    work: object          # Path of the variant work dir
    cache: object         # Path of the shared cache dir
    assets: dict
    bg_png: str
    rw: int = 0           # presenter stream size (px)
    rh: int = 0
    face: list = None     # face box in the presenter stream (px) or None
    is_first: bool = True
    is_last: bool = True
    mask_ok: bool = False
    report: list = None   # effect status messages for QC


def ease(expr_t, dur):
    """Smoothstep 0..1 as an ffmpeg expression of t over [0, dur]."""
    u = f"min(1,max(0,({expr_t})/{dur:.4f}))"
    return f"({u}*{u}*(3-2*{u}))"
