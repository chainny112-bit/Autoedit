"""Camera-move effects: Digital Zoom, Pull-back Reveal, Orbit (simulated), Vertigo (2.5D dolly zoom) and the
Zoom-through Cut transition. Camera effects return a Motion (zoom / rotation / pan expressions in clip time t);
the renderer multiplies all active motions into one scale/crop/rotate chain so effects combine cleanly."""
from dataclasses import dataclass

from .base import Effect, Param, ease

MAX_UPSCALE = 2.3   # beyond this the source has too few pixels; zoom is reduced (quality fallback)


@dataclass
class Motion:
    zoom: str = "1"
    rot: str = "0"        # radians
    panx: str = "0"       # fraction of width
    pany: str = "0"


def seg_t(cx):
    return f"(t+{cx.t_off:.4f})"


def limit_zoom(cx, amount):
    """Clamp extra zoom so total upscaling of source pixels stays acceptable."""
    crop = cx.item.get("crop")
    if not crop:
        return amount
    up = (cx.rw / cx.S) / max(1, crop[2])   # output px per source px at the base framing (full-res space)
    allowed = max(0.0, MAX_UPSCALE / up - 1)
    if amount > allowed + 1e-6:
        if cx.report is not None:
            cx.report.append({"seg": cx.seg["id"], "effect": "zoom_limit", "status": "adjusted",
                              "msg": f"ลดระดับซูมจาก {amount:.2f} เป็น {allowed:.2f} เพราะความละเอียดต้นฉบับไม่พอ"})
        return allowed
    return amount


class DigitalZoom(Effect):
    def camera(self, p, cx):
        A = limit_zoom(cx, p["amount"])
        if A <= 0.005:
            return None
        T, D = seg_t(cx), max(0.3, cx.seg_dur)
        mode = p["mode"]
        if mode == "in":
            z = f"(1+{A:.4f}*{ease(T, min(D * 0.6, 2.2))})"
        elif mode == "out":
            z = f"(1+{A:.4f}*(1-{ease(T, min(D * 0.6, 2.2))}))"
        elif mode == "pulse":   # quick push on the key word then settle
            z = f"(1+{A:.4f}*sin(PI*min(1,{T}/0.7))*exp(-{T}))"
        else:  # micro: slow continuous push that keeps a static shot alive
            z = f"(1+{A * 0.45:.4f}*min(1,{T}/{D:.3f}))"
        return Motion(zoom=z)

    def eligible(self, f, ctx):
        if f["layout_base"] not in ("full",):
            return None
        if f["importance"] >= 0.65:
            return 0.8, "ประโยคสำคัญ → ซูมเข้าเน้นประเด็น", {"mode": "in"}
        if f["topic_change"]:
            return 0.55, "เปลี่ยนหัวข้อ → ซูมออกเปิดพื้นที่", {"mode": "out"}
        return 0.3, "Micro zoom ให้ภาพนิ่งดูมีชีวิต", {"mode": "micro"}


class PullBack(Effect):
    def camera(self, p, cx):
        if cx.t_off > 0.01:     # only the opening of the segment
            return None
        z0 = 1 + limit_zoom(cx, p["start_zoom"] - 1)
        dur = p["duration"]
        return Motion(zoom=f"({z0:.4f}-({z0:.4f}-1)*{ease('t', dur)})")

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or f["dur"] < 2.0:
            return None
        if f["role"] == "hook":
            return 0.75, "เปิดเรื่อง → เริ่มใกล้แล้วดึงออกเปิดเผยภาพรวม", {}
        if f["role"] in ("turn", "conclusion") or f["mystery"]:
            return 0.6, "จุดเฉลย/หักมุม → Pull-back Reveal สร้างความรู้สึกเปิดเผย", {}
        return None


class Orbit(Effect):
    def camera(self, p, cx):
        T, D = seg_t(cx), max(1.0, cx.seg_dur)
        a = p["angle"] * 3.14159 / 180
        s = p["sweep"]
        # half-arc across the segment: rotate + lateral drift + slight push; rigid transforms only (no face warping)
        rot = f"({a:.5f}*cos(PI*min(1,{T}/{D:.3f})))"
        pan = f"({s:.4f}*cos(PI*min(1,{T}/{D:.3f})))"
        margin = 1 + abs(a) * 1.9 + abs(s) * 2.2   # enough over-scan that rotated corners never show
        return Motion(zoom=f"({margin:.4f}+0.03*min(1,{T}/{D:.3f}))", rot=rot, panx=pan)

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or f["dur"] < 2.5:
            return None
        if f["role"] == "hook" or ctx["genre"] in ("review", "promo"):
            return 0.55, "เน้นตัวบุคคล/สินค้าให้ดูมีมิติแบบ Cinematic", {}
        return 0.15, "เพิ่มมิติให้ช็อตผู้พูด", {}


class Vertigo(Effect):
    """With a person mask: true 2.5D dolly zoom (subject fixed, background recedes).
    Without: light scale + rotation simulation."""

    def camera(self, p, cx):
        if cx.mask_ok:
            return None   # handled by composite()
        T, D = seg_t(cx), max(0.8, min(cx.seg_dur, 2.5))
        A = limit_zoom(cx, p["amount"] * 0.6)
        return Motion(zoom=f"(1+{A:.4f}*{ease(T, D)})", rot=f"(0.006*sin(PI*min(1,{T}/{D:.3f})))")

    def composite(self, p, cx, idx):
        if not cx.mask_ok:
            return None
        rw, rh = cx.rw, cx.rh
        A = max(0.06, limit_zoom(cx, p["amount"]))
        Zf = 1 + A
        T, D = seg_t(cx), max(0.8, min(cx.seg_dur, 2.5))
        fx, fy = _face_frac(cx)
        zb = f"({Zf:.4f}-{A:.4f}*{ease(T, D)})"
        g = (f"[pres]split[pa][pb];[mask]scale={rw}:{rh}:flags=bicubic,format=gray[mk];"
             f"[pa][mk]alphamerge,{zoom_chain(rw, rh, f'{Zf:.4f}', fx, fy)},format=yuva420p[fg];"
             f"[pb]{zoom_chain(rw, rh, zb, fx, fy)},gblur=sigma=1.2[bg];[bg][fg]overlay=0:0:format=auto[v]")
        return [], g

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or f["dur"] < 1.5:
            return None
        if f["role"] == "turn" and (f["mystery"] or f["exclaim"]):
            return 0.7, "จุดหักมุม/ตึงเครียด → Dolly zoom สร้างความรู้สึกตกใจ", {}
        if f["mystery"] and f["importance"] >= 0.6:
            return 0.45, "ช่วงลึกลับที่สำคัญ → Vertigo แบบเบา", {}
        return None


class ZoomThrough(Effect):
    """Transition: the outgoing shot zooms into its focal point, the next shot emerges from the same point,
    joined by an expanding brand ring + flash so the connection point is clear."""

    def eligible(self, f, ctx):
        if f["is_first"]:
            return None
        if f["topic_change"] and f["role"] in ("turn", "steps", "point", "conclusion"):
            return 0.6, "เปลี่ยนหัวข้อ → ซูมทะลุเชื่อมฉาก", {}
        return None

    def ramp_out(self, p, cx):
        D = min(p["duration"], cx.d * 0.45)
        Zm = 1 + limit_zoom(cx, p["max_zoom"] - 1)
        return f"(1+{Zm - 1:.4f}*{ease(f't-{cx.d - D:.4f}', D)})"

    def ramp_in(self, p, cx):
        D = min(p["duration"], cx.d * 0.45)
        Zm = 1 + limit_zoom(cx, p["max_zoom"] - 1)
        return f"({Zm:.4f}-{Zm - 1:.4f}*{ease('t', D)})"

    def overlay_cut(self, sc, p, t_cut):
        from ..graphics import circle
        D = p["duration"]
        for k, (d0, a0) in enumerate(((140, 0x30), (90, 0x60))):
            sc.shape(t_cut - D * 0.6, t_cut + D, 540 - d0 / 2, 960 - d0 / 2, circle(d0), fill="#000000", fill_a=0xFF,
                     border=sc.primary if k == 0 else "#FFFFFF", bord=10 - 4 * k, border_a=a0, blur=4, layer=40,
                     extra="\\an7\\fscx20\\fscy20\\t(0,%d,\\fscx1400\\fscy1400)\\fad(60,120)" % int(D * 1600))
        sc.shape(t_cut - 0.06, t_cut + 0.1, 0, 0, "m 0 0 l 1080 0 l 1080 1920 l 0 1920", fill="#FFFFFF", fill_a=0x40,
                 layer=41, extra="\\fad(50,80)")


def _face_frac(cx):
    if not cx.face:
        return 0.5, 0.45
    f = cx.face
    fx = min(1, max(0, ((f[0] + f[2]) / 2) / cx.rw))
    fy = min(1, max(0, ((f[1] + f[3]) / 2) / cx.rh))
    return fx, fy


def zoom_chain(rw, rh, z, fx=0.5, fy=0.5):
    """Per-frame zoom (z = expression of t) about the point (fx, fy) using scale(eval=frame)+crop."""
    W2 = f"trunc({rw}*{z}/2)*2"
    H2 = f"trunc({rh}*{z}/2)*2"
    return (f"scale=w='{W2}':h='{H2}':eval=frame:flags=bicubic,"
            f"crop={rw}:{rh}:'({W2}-{rw})*{fx:.4f}':'({H2}-{rh})*{fy:.4f}'")


def motion_chain(motions, cx):
    """Combine several Motions into one filter chain for the presenter stream."""
    motions = [m for m in motions if m]
    if not motions:
        return ""
    z = "*".join(m.zoom for m in motions) if motions else "1"
    rot = "+".join(m.rot for m in motions if m.rot != "0") or None
    panx = "+".join(m.panx for m in motions if m.panx != "0") or None
    fx, fy = _face_frac(cx)
    if panx:
        fx_expr = f"max(0,min(1,{fx:.4f}+({panx})))"
    else:
        fx_expr = f"{fx:.4f}"
    rw, rh = cx.rw, cx.rh
    W2, H2 = f"trunc({rw}*({z})/2)*2", f"trunc({rh}*({z})/2)*2"
    chain = (f"scale=w='{W2}':h='{H2}':eval=frame:flags=bicubic,"
             f"crop={rw}:{rh}:'({W2}-{rw})*{fx_expr}':'({H2}-{rh})*{fy:.4f}'")
    if rot:
        chain += f",rotate=a='{rot}':ow={rw}:oh={rh}:fillcolor=black@1"
    return chain


def build():
    I = lambda name, label, lo, mid, hi, mn, mx: Param(name, "float", mid, label, mn, mx, by_intensity=(lo, mid, hi))
    return [
        DigitalZoom("digital_zoom", "Digital Zoom", "ซูมดิจิทัล", "camera", "real",
                    "ซูมเข้า/ออก/Micro zoom ต่อเฟรมด้วย FFmpeg (scale eval=frame + crop) จำกัดการขยายตามความละเอียดต้นฉบับ",
                    params=[Param("mode", "choice", "in", "รูปแบบ", choices=["in", "out", "micro", "pulse"]),
                            I("amount", "ระดับซูม", 0.06, 0.12, 0.2, 0.02, 0.4)],
                    inputs=["ภาพผู้พูด"], fallback="ลดระดับซูมอัตโนมัติถ้าความละเอียดไม่พอ", layout="full", attention=0.6,
                    cost=1.1),
        PullBack("pull_back", "Pull-back Reveal", "ดึงกล้องถอยออก", "camera", "real",
                 "เริ่มภาพระยะใกล้แล้วสเกลออกด้วย easing (2D scale animation) ต้นประโยค",
                 params=[I("start_zoom", "ซูมเริ่มต้น", 1.25, 1.45, 1.7, 1.1, 2.2),
                         I("duration", "ระยะเวลา (วินาที)", 1.0, 1.3, 1.6, 0.4, 3.0)],
                 inputs=["ภาพผู้พูด"], fallback="ลดซูมเริ่มต้นถ้าความละเอียดไม่พอ", layout="full", attention=1.0, cost=1.1),
        Orbit("orbit", "Orbit", "กล้องหมุนรอบ", "camera", "simulation",
              "จำลอง: หมุนภาพเล็กน้อย + เลื่อนแนวนอน + ดันเข้า (rigid transform ไม่บิดหน้า) — Orbit จริงต้องมีฟุตเทจหลายมุมหรือโมเดล novel-view synthesis",
              params=[I("angle", "มุมหมุน (องศา)", 0.8, 1.4, 2.2, 0.2, 4.0),
                      I("sweep", "ระยะเลื่อน", 0.03, 0.06, 0.09, 0.0, 0.15)],
              inputs=["ภาพผู้พูด"], fallback="—", layout="full", attention=1.0, cost=1.3),
        Vertigo("vertigo", "Vertigo", "Dolly Zoom", "camera", "simulation",
                "มี mask ตัวบุคคล: 2.5D — ตัวแบบคงขนาด ฉากหลังหดถอยออก (ไม่มีข้อมูลความลึกจริง); ไม่มี mask: scale + rotation เบาๆ",
                params=[I("amount", "ระดับ", 0.12, 0.2, 0.3, 0.05, 0.45)],
                enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "mask ตัวบุคคล (ถ้ามี)"],
                fallback="Scale + Perspective แบบเบา เมื่อแยกตัวบุคคลไม่ได้", layout="full", attention=1.4, cost=2.5),
        ZoomThrough("zoom_through", "Zoom-through Cut", "ซูมทะลุเปลี่ยนฉาก", "transition", "real",
                    "ฉากเดิมซูมเข้าจุดโฟกัส → ฉากใหม่ซูมออกจากจุดเดียวกัน + วงแหวนสีแบรนด์ขยายผ่านกล้องและแฟลชสั้น (2D)",
                    params=[I("duration", "ระยะเวลา", 0.25, 0.3, 0.38, 0.15, 0.6),
                            I("max_zoom", "ซูมสูงสุด", 1.6, 2.0, 2.5, 1.2, 3.0)],
                    inputs=["ฉากก่อนหน้าและฉากถัดไป"], fallback="เปลี่ยนเป็น Cut/Flash ถ้าคลิปสั้นเกินไป", attention=0.8,
                    cost=1.0),
    ]
