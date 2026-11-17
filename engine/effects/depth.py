"""Depth Stack: layered motion graphics around a talking head.

Behind the speaker (person mask):  a big chrome/silver word for the thought of each sentence, glowing sine waves
                                   or a gauge arc around the head.
In front of the speaker:           icon cards that pop in on the words they name, a small plate beside the head.

Without a mask the behind-layer cannot sit behind the head, so the silver word moves above the head (only if
there is room) and the waves/gauge are dropped rather than drawn across the face."""
import math

from .. import thai
from ..graphics import SAFE, circle, fit_size, rrect, text_width
from .base import Effect, Param
from .compositing import clip_ass

# top -> bottom colour stops of polished metal: bright rim, soft horizon dip, light reflected floor
CHROME_STOPS = [(0.0, "#FFFFFF"), (0.36, "#DCE0E4"), (0.50, "#A4ABB3"), (0.57, "#F1F3F5"), (0.80, "#C0C6CC"),
                (1.0, "#E6E9EC")]
WORD_FONT = "Kanit ExtraBold"
STEP = 1 / 20          # wave redraw interval (s)
NUM_CUES = ["ตัดสินใจ", "เลือก", "สุดท้าย", "ระดับ", "เปอร์เซ็นต์", "เพิ่มขึ้น", "ลดลง", "เป้า", "ทั้งหมด"]


# ------------------------------------------------------------------ helpers shared by both layers
def hero_word(seg):
    """The single word that carries the thought of a sentence (shown big behind the head)."""
    hl = [w for w in seg.get("highlight") or [] if w.strip()]
    words = [w for w in hl if thai.visual_len(w) >= 3 and not any(ch.isdigit() for ch in w)]
    if words:   # numbers go on the plate by the head; a lone digit would vanish behind it
        return words[0].upper()
    toks = [w["w"] for w in seg["words"]]
    cw = [w for w in thai.content_words(toks) if thai.visual_len(w) >= 2]
    if not cw:
        return ""
    return max(cw, key=lambda w: (thai.visual_len(w), -toks.index(w))).upper()


def word_index(seg, word):
    for i, w in enumerate(seg["words"]):
        if w["w"].upper() == word.upper():
            return i
    return None


def use_gauge(seg, p, feat=None):
    if p.get("backdrop") in ("gauge", "waves", "none"):
        return p["backdrop"] == "gauge"
    nums = (feat or {}).get("numbers")
    if nums is None:
        from .. import analyze as A
        nums = A.extract_numbers(seg)
    return bool(nums) or (seg.get("role") in ("conclusion", "turn")) or any(c in seg["text"] for c in NUM_CUES)


def _a(v):
    return f"&H{int(v):02X}&"


def _c(hex_rgb):
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"


def _ramp(u):
    for (u0, c0), (u1, c1) in zip(CHROME_STOPS, CHROME_STOPS[1:]):
        if u <= u1:
            k = (u - u0) / max(1e-6, u1 - u0)
            a, b = c0.lstrip("#"), c1.lstrip("#")
            return "#" + "".join(f"{round(int(a[i:i + 2], 16) * (1 - k) + int(b[i:i + 2], 16) * k):02X}"
                                 for i in (0, 2, 4))
    return CHROME_STOPS[-1][1]


def chrome_word(sc, t0, t1, x, y, word, size, extra="", layer=2, scale_x=86, bands=22, min_w=0):
    """Silver word: dark soft shadow (separation on bright backgrounds), white glow, and the glyphs painted in thin
    horizontal bands of a metal colour ramp (libass has no gradients)."""
    base = f"\\an5\\pos({x:.0f},{y:.0f})\\fn{WORD_FONT}\\fs{size}\\fscx{scale_x}\\shad0"
    tw = text_width(word, WORD_FONT, size) * scale_x / 100
    n = max(1, thai.visual_len(word) - 1)
    if min_w and tw < min_w:   # short word: spread the letters so it still frames the head instead of hiding
        base += f"\\fsp{min(70, (min_w - tw) / n):.0f}"
    sc.ev(t0, t1, "{" + base.replace(f"\\pos({x:.0f},{y:.0f})", f"\\pos({x:.0f},{y + size * 0.04:.0f})")
          + f"\\bord{size * 0.05:.0f}\\blur{size * 0.10:.0f}\\1c&H000000&\\3c&H000000&\\1a&H70&\\3a&H80&{extra}}}"
          + word, layer=layer)
    sc.ev(t0, t1, "{" + base + f"\\bord{size * 0.05:.0f}\\blur{size * 0.14:.0f}\\1c&HFFFFFF&\\3c&HFFFFFF&"
          f"\\1a&HE0&\\3a&HD8&{extra}}}" + word, layer=layer + 1)
    top, h = y - size * 0.50, size * 1.0
    for k in range(bands):
        y0 = top + h * k / bands if k else y - size
        y1 = top + h * (k + 1) / bands + 1 if k < bands - 1 else y + size
        col = _ramp((k + 0.5) / bands)
        sc.ev(t0, t1, "{" + base + f"\\bord1\\1c{_c(col)}\\3c&H6A6560&\\3a&H70&"
              f"\\clip(0,{y0:.0f},1080,{y1:.0f}){extra}}}" + word, layer=layer + 2)


def _wave_path(y, amp, wl, phase, env_cx, env_w):
    pts = []
    for x in range(-20, 1101, 18):
        env = 0.28 + 0.72 * math.exp(-((x - env_cx) / env_w) ** 2)
        pts.append((x, y + amp * env * math.sin(2 * math.pi * x / wl + phase)))
    back = list(reversed(pts))   # retrace the curve so the closed contour has no straight closing edge
    return "m %d %d " % pts[0] + " ".join("l %d %d" % p for p in pts[1:] + back)


def waves(sc, t0, t1, t_global, y, cx, color, color2, intensity=1.0):
    """Two glowing sine waves crossing the frame at head height; the bulge stays behind the head."""
    specs = [(56 * intensity, 520, 2.6, 0.0, color, 3), (38 * intensity, 380, -1.9, 1.7, color2, 2)]
    t = t0
    while t < t1 - 0.01:
        t2 = min(t1, t + STEP)
        tg = t_global + (t - t0)
        for amp, wl, speed, off, col, bw in specs:
            path = _wave_path(y, amp * (0.85 + 0.15 * math.sin(tg * 1.3 + off)), wl, tg * speed + off, cx, 330)
            sc.ev(t, t2, "{\\an7\\pos(0,0)\\p1\\shad0\\1a&HFF&\\bord%d\\blur9\\3c%s\\3a&H70&}%s{\\p0}"
                  % (bw * 4, _c(col), path), layer=1)
            sc.ev(t, t2, "{\\an7\\pos(0,0)\\p1\\shad0\\1a&HFF&\\bord%d\\blur0.8\\3c%s}%s{\\p0}"
                  % (bw, _c(col), path), layer=2)
        t = t2


def _arc_piece(cx, cy, r0, r1, a0, a1):
    p = lambda r, a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    pts = [p(r1, a0), p(r1, a1), p(r0, a1), p(r0, a0)]
    return "m %d %d " % pts[0] + " ".join("l %d %d" % q for q in pts[1:])


def gauge(sc, t0, t1, cx, cy, R, color, animate=True, frac=0.78):
    """Speedometer arc over the head: ticks, track, a glowing fill that sweeps up and a needle."""
    A0, A1 = 192.0, 348.0
    sweep = (A1 - A0) * frac
    fade = "\\fad(200,0)" if animate else ""
    for k in range(14):
        a = A0 + (A1 - A0) * k / 13
        ln = 22 if k % 3 == 0 else 12
        sc.ev(t0, t1, "{\\an7\\pos(0,0)\\p1\\shad0\\bord0\\1c&HFFFFFF&\\1a&H70&%s}%s{\\p0}"
              % (fade, _arc_piece(cx, cy, R + 14, R + 14 + ln, a - 0.5, a + 0.5)), layer=1)
    sc.ev(t0, t1, "{\\an7\\pos(0,0)\\p1\\shad0\\bord0\\1c&HFFFFFF&\\1a&HC8&%s}%s{\\p0}"
          % (fade, _arc_piece(cx, cy, R - 4, R + 4, A0, A1)), layer=1)
    n = 26
    for k in range(n):
        a, b = A0 + sweep * k / n, A0 + sweep * (k + 1) / n + 0.6
        ta = t0 + (0.25 + 0.75 * k / n if animate else 0)
        piece = _arc_piece(cx, cy, R - 7, R + 7, a, b)
        sc.ev(ta, t1, "{\\an7\\pos(0,0)\\p1\\shad0\\bord8\\blur10\\1c%s\\3c%s\\1a&H40&\\3a&H90&}%s{\\p0}"
              % (_c(color), _c(color), piece), layer=1)
        sc.ev(ta, t1, "{\\an7\\pos(0,0)\\p1\\shad0\\bord0\\1c%s}%s{\\p0}" % (_c(color), piece), layer=2)
    # needle: drawn at the start angle, rotated clockwise around the hub (ASS \frz is counter-clockwise)
    a = math.radians(A0)
    tip = (cx + (R + 18) * math.cos(a), cy + (R + 18) * math.sin(a))
    base_r = R * 0.62
    tail = (cx + base_r * math.cos(a), cy + base_r * math.sin(a))
    needle = "m %d %d l %d %d" % (tail[0], tail[1], tip[0], tip[1])
    needle += " l %d %d l %d %d" % (tail[0], tail[1] + 1, tail[0], tail[1])
    rot = ("\\frz0\\t(250,1000,0.6,\\frz%.1f)" % -sweep) if animate else "\\frz%.1f" % -sweep
    sc.ev(t0, t1, "{\\an7\\pos(0,0)\\org(%d,%d)\\p1\\shad0\\1a&HFF&\\bord2.5\\blur0.6\\3c&HFFFFFF&%s%s}%s{\\p0}"
          % (cx, cy, fade, rot, needle), layer=3)
    sc.ev(t0, t1, "{\\an7\\pos(0,0)\\org(%d,%d)\\p1\\shad0\\1a&HFF&\\bord7\\blur8\\3c%s\\3a&H80&%s%s}%s{\\p0}"
          % (cx, cy, _c(color), fade, rot, needle), layer=2)


# ------------------------------------------------------------------ vector icons (drawn in a 40x40 box)
ICONS = {
    "check": "m 6 21 l 11 16 l 17 22 l 31 8 l 36 13 l 17 32",
    "star": "m 20 2 l 25 14 l 38 15 l 28 24 l 31 37 l 20 30 l 9 37 l 12 24 l 2 15 l 15 14",
    "bolt": "m 23 2 l 7 23 l 18 23 l 15 38 l 33 15 l 22 15 l 25 2",
    "target": "m 20 3 b 30 3 37 10 37 20 b 37 30 30 37 20 37 b 10 37 3 30 3 20 b 3 10 10 3 20 3 "
              "m 20 11 b 15 11 11 15 11 20 b 11 25 15 29 20 29 b 25 29 29 25 29 20 b 29 15 25 11 20 11",
    "up": "m 20 3 l 36 21 l 26 21 l 26 37 l 14 37 l 14 21 l 4 21",
    "spark": "m 20 2 l 24 16 l 38 20 l 24 24 l 20 38 l 16 24 l 2 20 l 16 16",
}
ICON_ORDER = ["star", "bolt", "target", "check", "up", "spark"]


def icon_tile(sc, t0, t1, x, y, s, icon, color, extra="", layer=30):
    """Glowing rounded tile in the brand colour with a white glyph."""
    sc.shape(t0, t1, x, y, rrect(s, s, s * 0.26), fill=color, fill_a=0x60, blur=s * 0.25, layer=layer, extra=extra)
    sc.shape(t0, t1, x, y, rrect(s, s, s * 0.26), fill=color, border="#FFFFFF", bord=1.2, border_a=0x90,
             layer=layer + 1, extra=extra)
    sc.shape(t0, t1, x + 2, y + 2, rrect(s - 4, s * 0.45, s * 0.22), fill="#FFFFFF", fill_a=0xB8, layer=layer + 2,
             extra=extra)
    k = s * 0.62 / 40
    sc.shape(t0, t1, x + s * 0.19, y + s * 0.19, ICONS[icon], fill="#FFFFFF", layer=layer + 3,
             extra=extra + "\\fscx%d\\fscy%d" % (k * 100, k * 100))


class DepthStack(Effect):
    # ---- behind the speaker (needs the person mask) ----
    def composite(self, p, cx, idx):
        if not cx.mask_ok:
            return None
        S = cx.S
        rw, rh = cx.rw, cx.rh
        f = [v / S for v in cx.face] if cx.face else [380, 520, 700, 900]
        fw, fh = f[2] - f[0], f[3] - f[1]
        hx = (f[0] + f[2]) / 2
        word = hero_word(cx.seg)
        first = cx.t_off < 0.05
        gauge_on = use_gauge(cx.seg, p)
        k_int = {"low": 0.75, "medium": 1.0, "high": 1.25}.get(cx.intensity, 1.0)
        primary = cx.settings.get("accent", "#33E1D0")
        second = cx.settings.get("accent2", "#9AF6EC")

        def build(sc):
            if p.get("backdrop") != "none":
                if gauge_on:
                    R = max(220, min(400, fw * 1.15))
                    gauge(sc, 0, cx.d, hx, f[1] + fh * 0.55, R, primary, animate=first)
                else:
                    waves(sc, 0, cx.d, cx.t_off, f[1] + fh * 0.18, hx, primary, second, k_int)
            if word:
                size = fit_size(word, WORD_FONT, int(p["word_size"]), 1000 / 0.86, min_size=120)
                y = max(SAFE["top"] + size * 0.45, f[1] - size * 0.08)
                hold = int(p["hold"] * 1000)
                dim = "\\t(%d,%d,\\alpha&HB4&)" % (max(0, hold - cx.t_off * 1000), max(0, hold - cx.t_off * 1000) + 450)
                if cx.t_off * 1000 > hold + 450:
                    dim = "\\alpha&HB4&"
                intro = "\\fad(120,0)\\fscy115\\t(0,220,\\fscy100)" if first else ""
                chrome_word(sc, 0, cx.d, 540, y, word, size, extra=dim + intro, min_w=min(980, fw * 1.9))

        g = (f"[pres]split[pa][pb];[pa]{clip_ass(cx, f'depth_{cx.seg['id']}_{cx.item['ci']}', build)}[behind];"
             f"[mask]scale={rw}:{rh}:flags=bicubic,format=gray[mk];[pb][mk]alphamerge[fg];"
             f"[behind][fg]overlay=0:0:format=auto[v]")
        cx.seg.setdefault("_runtime", {})["depth_behind"] = True
        return [], g

    # ---- in front of the speaker ----
    def overlay(self, sc, p, ox):
        seg = ox.seg
        face = ox.face or [380, 520, 700, 900]
        fw, fh = face[2] - face[0], face[3] - face[1]
        hero = hero_word(seg)
        t0, t1 = ox.t0, ox.t1
        if not ox.rt.get("depth_behind") and hero:
            # fallback: no mask — the word can't go behind the head; put it above the head if it fits there
            size = fit_size(hero, WORD_FONT, 170, 1000 / 0.86, min_size=90)
            y = face[1] - size * 0.62
            if y - size * 0.5 > SAFE["top"]:
                chrome_word(sc, t0 + 0.05, min(t1, t0 + 0.05 + p["hold"] + 0.4), 540, y, hero, size,
                            extra="\\fad(120,300)", layer=24)
        # icon cards: the sentence's other key words, popping in as they are spoken
        words = []
        for k in (ox.feat.get("keywords") or []) + [w for w in seg.get("highlight") or []]:
            if k.upper() != hero and k not in words and 2 <= thai.visual_len(k) <= 22:
                words.append(k)
        items = []
        for w in words:
            i = word_index(seg, w)
            items.append((ox.word_out(i) - 0.08 if i is not None else None, w))
        items = items[: int(p["cards"])]
        cap_top = ox.sub_y - ox.sub_size * 0.6 - 30
        row, s = 82, 62
        y0 = face[3] + 70
        n_fit = int((cap_top - y0) // row)
        items = items[: max(0, n_fit)]
        if items:
            x0 = min(max(SAFE["left"] + 20, (face[0] + face[2]) / 2 - 250), 420)
            for k, (ta, w) in enumerate(items):
                ta = t0 + 0.25 + 0.35 * k if ta is None else ta
                ta = min(max(t0 + 0.1, ta), t1 - 0.5)
                y = y0 + k * row
                pop = "\\fad(140,220)"
                icon_tile(sc, ta, t1, x0, y, s, ICON_ORDER[k % len(ICON_ORDER)], sc.primary, extra=pop)
                label = thai.short_title(w, 22)
                ls = fit_size(label, "Kanit SemiBold", 40, 1010 - (x0 + s + 22))
                sc.text(ta, t1, x0 + s + 22, y + s / 2, label, size=ls, family="Kanit SemiBold", an=4,
                        color="#FFFFFF", bord=0, shad=2, layer=33,
                        extra=pop + "\\4a&H40&\\move(%d,%d,%d,%d,0,200)" % (x0 + s + 52, y + s / 2, x0 + s + 22,
                                                                            y + s / 2))
                sc.boxes.append((ta, t1, x0, y, x0 + s + 22 + text_width(label, "Kanit SemiBold", ls), y + s, "icon_card"))
        # plate by the head: a number if one is said, otherwise the last unused key word
        nums = ox.feat.get("numbers") or []
        used = {w for _, w in items}
        plate, pi = None, None
        if nums:
            plate, pi = nums[0][1] + (" " + nums[0][2] if nums[0][2] else ""), nums[0][0]
        else:
            rest = [w for w in words if w not in used]
            if rest:
                plate = rest[-1]
                pi = word_index(seg, plate)
        if plate and p["plate"]:
            plate = thai.short_title(plate, 16)
            size = 30
            pw = text_width(plate, "Kanit SemiBold", size) + 74
            ph = 54
            right = face[2] + 18 + pw <= SAFE["right"]
            px = face[2] + 18 if right else max(SAFE["left"], face[0] - 18 - pw)
            py = face[1] + fh * 0.30
            if right or face[0] - 18 - pw >= SAFE["left"]:
                ta = ox.word_out(pi) - 0.1 if pi is not None else t0 + 0.4
                ta = min(max(t0 + 0.1, ta), t1 - 0.5)
                pop = "\\fad(140,200)"
                sc.shape(ta, t1, px, py, rrect(pw, ph, 14), fill="#0B0D10", fill_a=0x38, border="#FFFFFF", bord=1.5,
                         border_a=0xA0, layer=30, extra=pop)
                sc.shape(ta, t1, px + 16, py + 15, rrect(24, 24, 6), fill="#FFFFFF", fill_a=0x10, layer=31, extra=pop)
                sc.text(ta, t1, px + 52, py + ph / 2, plate, size=size, family="Kanit SemiBold", an=4, bord=0,
                        shad=0, layer=31, extra=pop)
                sc.boxes.append((ta, t1, px, py, px + pw, py + ph, "plate"))

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or not f["face"] or f["dur"] < 0.9:
            return None
        if f["role"] == "hook" or f["importance"] >= 0.6:
            return 0.75, "ประโยคสำคัญ → คำเงินใหญ่หลังศีรษะ + คลื่น/เกจเรืองแสง + การ์ดไอคอนตามคำพูด", {}
        if f["keywords"]:
            return 0.5, "ทุกความคิดมีคำหลัก → วางคำเงินหลังศีรษะ (Depth Stack)", {}
        return None


def build():
    return [
        DepthStack("depth_stack", "Depth Stack", "คำเงินหลังศีรษะ + กราฟิกซ้อนชั้น", "composite", "real",
                   "หลังผู้พูด (mask): คำสำคัญตัวใหญ่สีเงินโครเมียม + คลื่นเรืองแสงหรือเกจรอบศีรษะ · หน้าผู้พูด: การ์ดไอคอนโผล่ตามคำที่พูด และป้ายเล็กข้างศีรษะ",
                   params=[Param("word_size", "int", 300, "ขนาดคำเงิน", 160, 380, by_intensity=(240, 300, 340)),
                           Param("hold", "float", 1.4, "คำเงินสว่างนาน (วินาที)", 0.6, 4.0),
                           Param("backdrop", "choice", "auto", "ฉากหลังผู้พูด",
                                 choices=["auto", "waves", "gauge", "none"]),
                           Param("cards", "int", 3, "จำนวนการ์ดไอคอน", 0, 4, by_intensity=(2, 3, 4)),
                           Param("plate", "bool", True, "ป้ายข้างศีรษะ")],
                   enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "mask ตัวบุคคล", "คำสำคัญ/ตัวเลขในบทพูด"],
                   fallback="ไม่มี mask → คำเงินย้ายไปเหนือศีรษะ (ถ้ามีที่ว่าง) และไม่วาดคลื่น/เกจทับใบหน้า",
                   layout="full", attention=1.5, cost=3.0),
    ]
