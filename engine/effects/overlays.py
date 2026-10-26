"""Overlay effects on the presenter shot: Headline Wall, Doodle Boil, Glassy Type, Cover Story."""
import datetime
import math
import random

from .. import thai
from ..graphics import SAFE, circle, esc, fit_size, rrect, text_width, wrap
from .base import Effect, Param
from .compositing import _even, bg_cover, clip_ass

TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน",
             "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def _overlaps(r, boxes, pad=24):
    x0, y0, x1, y1 = r
    for b in boxes:
        if not (x1 + pad < b[0] or x0 - pad > b[2] or y1 + pad < b[1] or y0 - pad > b[3]):
            return True
    return False


class HeadlineWall(Effect):
    def overlay(self, sc, p, ox):
        f = ox.feat
        words = []
        for n in f.get("numbers") or []:
            words.append((n[1] + (" " + n[2] if n[2] else ""), n[0], 3))
        hl = ox.seg.get("highlight") or []
        for k in f.get("keywords") or []:
            if k not in hl and thai.visual_len(k) < 4:
                continue    # weak short words make noise, not headlines
            idx = next((i for i, w in enumerate(ox.seg["words"]) if w["w"] == k), None)
            words.append((k, idx, 2 if k in hl else 1))
        seen, items = set(), []
        for w, i, imp in words:
            if w not in seen and thai.visual_len(w) >= 2:
                seen.add(w)
                items.append((w, i, imp))
        items = sorted(items, key=lambda x: -x[2])[: int(p["count"])]
        if not items:
            return
        face = ox.face or [380, 520, 700, 900]
        blocked = [[face[0] - 40, face[1] - 60, face[2] + 40, face[3] + 80],
                   [0, ox.sub_y - ox.sub_size, 1080, ox.sub_y + ox.sub_size]]
        sizes = {3: 70, 2: 54, 1: 42}
        placed = []
        slots = [(x, y) for y in range(SAFE["top"] + 60, 1240, 110) for x in (70, 560)]
        random.Random(ox.seg["id"]).shuffle(slots)
        slots.sort(key=lambda s: abs(s[1] - (face[1] + face[3]) / 2))   # cluster around the head
        for w, i, imp in items:
            size = sizes[imp]
            tw = text_width(w, "Kanit ExtraBold", size) + 56
            if tw > 470:
                size = fit_size(w, "Kanit ExtraBold", size, 470 - 56)
                tw = text_width(w, "Kanit ExtraBold", size) + 56
            h = size * 1.45
            for sx, sy in slots:
                x = sx if sx < 500 else 1010 - tw
                r = [x, sy, x + tw, sy + h]
                if not _overlaps(r, blocked + placed):
                    placed.append(r)
                    a = ox.word_out(i) - 0.15 if i is not None else ox.t0 + 0.2 + 0.2 * len(placed)
                    a = min(max(ox.t0 + 0.05, a), ox.t1 - 0.4)
                    pop = "\\fad(150,200)\\fscx70\\fscy70\\t(0,160,\\fscx106\\fscy106)\\t(160,240,\\fscx100\\fscy100)"
                    drift = "\\move(%d,%d,%d,%d)" % (x, sy, x + random.Random(w).choice([-14, 14]), sy - 10)
                    if imp >= 2:
                        sc.shape(a, ox.t1, x, sy, rrect(tw, h, h / 2), fill=sc.primary, fill_a=0x00 if imp == 3 else 0x30,
                                 layer=8, extra=pop + drift)
                    else:
                        sc.shape(a, ox.t1, x, sy, rrect(tw, h, h / 2), fill="#000000", fill_a=0x60,
                                 border="#FFFFFF", bord=2, border_a=0x60, layer=8, extra=pop + drift)
                    ttag = "\\move(%d,%d,%d,%d)" % (x + tw / 2, sy + h / 2, x + tw / 2 + (r[0] - x), sy + h / 2 - 10)
                    sc.text(a, ox.t1, x + tw / 2, sy + h / 2, w, size=size, color="#FFFFFF", bord=0 if imp >= 2 else 2,
                            shad=0, layer=9, extra=pop.replace("\\fscx70", "\\fscx70") + "\\an5" +
                            "\\move(%d,%d,%d,%d)" % (x + tw / 2, sy + h / 2,
                                                     x + tw / 2 + random.Random(w).choice([-14, 14]), sy + h / 2 - 10))
                    sc.boxes.append((a, ox.t1, r[0], r[1], r[2], r[3], "headline"))
                    break

    def eligible(self, f, ctx):
        if f["layout_base"] != "full":
            return None
        n = len(f["keywords"]) + len(f["numbers"])
        if n >= 3 and ctx["genre"] in ("news", "story"):
            return 0.65, "ประโยคมีคำสำคัญหลายคำ → Headline Wall รอบผู้พูด เรียงลำดับความสำคัญ", {}
        if n >= 3:
            return 0.4, "สรุปประเด็นหลายคำ → Headline Wall", {}
        return None


class DoodleBoil(Effect):
    def overlay(self, sc, p, ox):
        rng = random.Random(ox.seg["id"])
        boil = 1 / p["boil_fps"]
        drawn = 0
        for ph in ox.phrases:
            hl = [i for i, w in enumerate(ph["parts"]) if w["hl"]]
            if not hl or drawn >= p["count"]:
                continue
            i = hl[0]
            sz = ph["size"]
            fnt = ph.get("font", "Kanit ExtraBold")
            total = text_width(ph["text"], fnt, sz)
            pre = "".join(w["w"] for w in ph["parts"][:i])
            word = "".join(w["w"] for w in ph["parts"][i:hl[-1] + 1])
            x0 = 540 - total / 2 + text_width(pre, fnt, sz)
            x1 = x0 + text_width(word, fnt, sz)
            y = ph["y"]
            a = ph["parts"][i]["s"] if ph["parts"][i]["s"] is not None else ph["s"]
            a = max(ph["s"], a)
            e = ph["e"]
            if e - a < 0.3:
                continue
            drawn += 1
            col = "#FFFFFF" if p["color"] == "white" else sc.primary
            kind = "circle" if drawn % 2 else "underline"
            t = a
            k = 0
            while t < e:
                t2 = min(e, t + boil)
                r = random.Random(f"{ox.seg['id']}{drawn}{k}")
                if kind == "circle":
                    path = _wobbly_ellipse((x0 + x1) / 2, y, (x1 - x0) / 2 + 26, sz * 0.62, r)
                else:
                    path = _wobbly_line(x0 - 10, y + sz * 0.62, x1 + 10, y + sz * 0.62, r)
                reveal = "\\clip(0,0,%d,1920)\\t(0,%d,\\clip(0,0,1080,1920))" % (x0 - 40, 260) if k == 0 else ""
                sc.ev(t, t2, "{\\an7\\pos(0,0)\\p1\\bord5\\shad0\\blur0.6\\1a&HFF&\\3c%s%s}%s{\\p0}" % (
                    _c(col), reveal, path), layer=22)
                k += 1
                t = t2
            # hand-drawn arrow from free space towards the word (never over the face)
            if p["arrows"] and ox.face:
                side = -1 if (x0 + x1) / 2 > 540 else 1
                ax = (x0 - 150) if side < 0 else (x1 + 150)
                ax = min(1000, max(80, ax))
                ay = y - sz * 1.6
                if not (ox.face[0] - 30 < ax < ox.face[2] + 30 and ox.face[1] - 30 < ay < ox.face[3] + 30):
                    t, k = a + 0.15, 0
                    tx = x0 - 20 if side < 0 else x1 + 20
                    while t < e:
                        t2 = min(e, t + boil)
                        r = random.Random(f"a{ox.seg['id']}{drawn}{k}")
                        path = _wobbly_arrow(ax, ay, tx, y - sz * 0.55, r)
                        sc.ev(t, t2, "{\\an7\\pos(0,0)\\p1\\bord4\\shad0\\1a&HFF&\\3c%s}%s{\\p0}" % (_c(sc.second), path),
                              layer=22)
                        k += 1
                        t = t2

    def eligible(self, f, ctx):
        if f["layout_base"] not in ("full", "pip"):
            return None
        if f["highlight"] and (f["importance"] >= 0.5 or ctx["genre"] == "howto"):
            return 0.5, "ชี้จุดสำคัญด้วยเส้นวาดมือรอบคำที่เน้น", {}
        return None


def _c(hex_rgb):
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"


def _wobbly_ellipse(cx, cy, rx, ry, r):
    pts = []
    n = 22
    start = r.uniform(0, 6.28)
    for i in range(n + 3):   # overshoot past the start like a real pen stroke
        a = start + 2 * math.pi * i / n
        j = 1 + r.uniform(-0.05, 0.05)
        pts.append((cx + rx * j * math.cos(a), cy + ry * j * math.sin(a)))
    return "m %d %d " % pts[0] + " ".join("l %d %d" % p for p in pts[1:])


def _wobbly_line(x0, y0, x1, y1, r):
    n = 10
    pts = [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n + r.uniform(-4, 4)) for i in range(n + 1)]
    pts += [(x1 - 30, y1 + 10 + r.uniform(-3, 3))]
    return "m %d %d " % pts[0] + " ".join("l %d %d" % p for p in pts[1:])


def _wobbly_arrow(x0, y0, x1, y1, r):
    mx, my = (x0 + x1) / 2 + r.uniform(-20, 20), min(y0, y1) - 40 + r.uniform(-8, 8)
    pts = []
    for i in range(13):
        t = i / 12
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t * t * x1 + r.uniform(-2.5, 2.5)
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t * t * y1 + r.uniform(-2.5, 2.5)
        pts.append((x, y))
    ang = math.atan2(y1 - pts[-2][1], x1 - pts[-2][0])
    h1 = (x1 - 30 * math.cos(ang - 0.5), y1 - 30 * math.sin(ang - 0.5))
    h2 = (x1 - 30 * math.cos(ang + 0.5), y1 - 30 * math.sin(ang + 0.5))
    body = "m %d %d " % pts[0] + " ".join("l %d %d" % p for p in pts[1:])
    return body + " m %d %d l %d %d l %d %d" % (h1[0], h1[1], x1, y1, h2[0], h2[1])


class GlassyType(Effect):
    @staticmethod
    def rect(seg, face, sub_y):
        """Glass panel rect (1080x1920 space) that avoids the face and the subtitle band."""
        h = 230
        y = 1040
        if face and face[3] + 40 > y:
            y = face[3] + 40
        if y + h > sub_y - 90:
            y = SAFE["top"] + 90
            if face and y + h > face[1] - 20:
                y = max(SAFE["top"], sub_y - 90 - h)
        return [90, int(y), 900, h]

    def post(self, p, cx):
        g = cx.seg.get("_runtime", {}).get("glass")
        if not g:
            return None
        S = cx.S
        x, y, w, h = (_even(v * S) for v in g)
        return (f"[vin]split[ga][gb];[gb]crop={w}:{h}:{x}:{y},boxblur={max(4, int(22 * S))}:2,"
                f"eq=brightness=-0.13:saturation=1.15[gbl];[ga][gbl]overlay={x}:{y}[vout]")

    def overlay(self, sc, p, ox):
        g = ox.rt.get("glass")
        if not g:
            return
        x, y, w, h = g
        t0, t1 = ox.t0 + 0.05, ox.t1
        fade = "\\fad(220,180)"
        main = (ox.seg.get("title") or "").strip()
        nums = ox.feat.get("numbers") or []
        if not main and nums:
            n = nums[0]
            main = n[1] + (" " + n[2] if n[2] else "")
        if not main:
            main = thai.key_clause(ox.seg["text"], ox.seg.get("highlight") or [], 18)
        sub = thai.short_title(nums[0][3], 24) if nums and main.startswith(nums[0][1]) else ""
        # frosted tint, top sheen, hairline border, brand glow — readable on any footage
        sc.shape(t0, t1, x, y, rrect(w, h, 34), fill="#FFFFFF", fill_a=0xE4, layer=10, extra=fade)
        sc.shape(t0, t1, x + 6, y + 4, rrect(w - 12, h * 0.42, 30), fill="#FFFFFF", fill_a=0xD2, blur=6, layer=11,
                 extra=fade)
        sc.shape(t0, t1, x, y, rrect(w, h, 34), fill="#000000", fill_a=0xFF, border=sc.primary, bord=9,
                 border_a=0xB0, blur=14, layer=9, extra=fade)
        sc.shape(t0, t1, x, y, rrect(w, h, 34), fill="#000000", fill_a=0xFF, border="#FFFFFF", bord=2,
                 border_a=0x70, layer=12, extra=fade)
        size = fit_size(main, "Kanit ExtraBold", 96, w - 80)
        sc.text(t0, t1, x + w / 2, y + (h / 2 if not sub else h * 0.42), main, size=size, color="#FFFFFF", bord=0,
                shad=2, layer=13, extra=fade + "\\4c&H000000&\\4a&H90&\\fscx90\\fscy90\\t(0,220,\\fscx100\\fscy100)")
        if sub:
            ss = fit_size(sub, "Kanit SemiBold", 40, w - 80)
            sc.text(t0 + 0.15, t1, x + w / 2, y + h * 0.78, sub, size=ss, family="Kanit SemiBold", color="#F2F2F2",
                    bord=0, shad=1, layer=13, extra=fade)
        sc.shape(t0, t1, x + w - 46, y + 22, circle(18), fill=sc.second, layer=13, extra=fade)
        sc.boxes.append((t0, t1, x, y, x + w, y + h, "glass"))

    def eligible(self, f, ctx):
        if f["layout_base"] != "full":
            return None
        if f["role"] == "conclusion":
            return 0.55, "สรุปท้ายคลิป → ข้อความกระจกโปร่งแสงอ่านง่าย", {}
        if f["numbers"] and f["importance"] >= 0.5:
            return 0.5, "ตัวเลขสำคัญ → Glassy Type", {}
        if f["role"] == "hook":
            return 0.35, "หัวข้อหลัก → Glassy Type", {}
        return None


class CoverStory(Effect):
    def masthead(self, ox_or_settings):
        st = ox_or_settings
        return (st.get("brand_name") or "RED RABBIT").upper()

    def composite(self, p, cx, idx):
        if not cx.mask_ok or not cx.is_first:
            return None
        name = self.masthead(cx.settings)
        rw, rh = cx.rw, cx.rh

        def build(sc):
            size = fit_size(name, "Kanit ExtraBold", 230, 1000)
            sc.atext(0, cx.d, 540, SAFE["top"] + 40 + size * 0.5, name, size=size, bord=4, layer=3, glow=False,
                     extra="\\fad(250,0)")
        g = (f"[pres]split[pa][pb];[pa]{clip_ass(cx, f'cover_{cx.seg['id']}', build)}[bgc];"
             f"[mask]scale={rw}:{rh}:flags=bicubic,format=gray[mk];[pb][mk]alphamerge[fg];"
             f"[bgc][fg]overlay=0:0:format=auto[v]")
        cx.seg.setdefault("_runtime", {})["cover_behind"] = True
        return [], g

    def overlay(self, sc, p, ox):
        t0, t1 = ox.t0 + 0.05, min(ox.t1, ox.t0 + max(3.0, p["hold"]))
        fade = "\\fad(250,250)"
        name = self.masthead(ox.settings)
        size = fit_size(name, "Kanit ExtraBold", 230, 1000)
        top = SAFE["top"] + 40
        if not ox.rt.get("cover_behind"):
            sc.atext(t0, t1, 540, top + size * 0.5, name, size=size, bord=4, layer=14, glow=False, extra=fade)
        today = datetime.date.today()
        issue = f"ฉบับ {TH_MONTHS[today.month - 1]} {today.year + 543}"
        sc.shape(t0, t1, 60, top + size * 1.02, rrect(960, 4, 2), fill="#FFFFFF", layer=14, extra=fade)
        sc.text(t0, t1, 60, top + size * 1.02 + 34, issue, size=34, family="Kanit SemiBold", an=4, bord=2, shad=0,
                layer=14, extra=fade)
        sc.shape(t0, t1, 1000, top + size * 1.02 + 22, circle(22), fill=sc.second, layer=14, extra=fade)
        # cover lines: real upcoming points of this video, small, on the left edge away from the face
        face = ox.face or [400, 500, 700, 900]
        ly = top + size * 1.02 + 110
        for k, line in enumerate(ox.cover_lines[:3]):
            lines = wrap(line, "Kanit SemiBold", 36, max(220, face[0] - 90), 2)
            for j, ln in enumerate(lines):
                if ly > face[3] + 200:
                    break
                sc.text(t0 + 0.25 + 0.2 * k, t1, 60, ly, ln, size=36, family="Kanit SemiBold", an=4,
                        color="#FFFFFF", bord=3, shad=0, layer=14, extra=fade)
                ly += 48
            sc.shape(t0 + 0.25 + 0.2 * k, t1, 60, ly - 8, rrect(80, 5, 2), fill=sc.primary, layer=14, extra=fade)
            ly += 34
        # headline above the subtitle band, on a dark gradient for legibility
        head = (ox.seg.get("title") or thai.key_clause(ox.seg["text"], ox.seg.get("highlight") or [], 22)).strip()
        hy = ox.sub_y - ox.sub_size - 120
        for k in range(4):
            sc.shape(t0, t1, 0, hy - 140 + k * 70, rrect(1080, 70 + 360 - k * 70, 0), fill="#000000",
                     fill_a=0xC0 - k * 0x18, layer=13, extra=fade)
        hl = wrap(head, "Kanit ExtraBold", 92, 960, 2)
        hs = 92 if len(hl) == 1 else 76
        for k, ln in enumerate(hl):
            yy = hy - (len(hl) - 1 - k) * hs * 1.15
            sc.text(t0 + 0.2, t1, 60, yy, ln, size=fit_size(ln, "Kanit ExtraBold", hs, 960), an=4, color="#FFFFFF",
                    bord=3, shad=0, layer=15, extra=fade + "\\move(30,%d,60,%d,0,300)" % (yy, yy))
        sc.boxes.append((t0, t1, 60, hy - hs * 1.2 * len(hl), 1020, hy + hs * 0.6, "cover"))

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or not f["face"]:
            return None
        if f["role"] == "hook":
            return 0.6 if ctx["genre"] in ("promo", "review", "story") else 0.45, \
                "เปิดคลิป/แนะนำตอน → จัดองค์ประกอบแบบหน้าปกนิตยสาร", {}
        return None


def build():
    return [
        HeadlineWall("headline_wall", "Headline Wall", "กำแพงพาดหัว", "overlay", "real",
                     "คำสำคัญ/ตัวเลขจากบทพูดลอยรอบผู้พูด หลบใบหน้าและซับ ขนาดตามลำดับความสำคัญ โผล่ตามจังหวะพูด",
                     params=[Param("count", "int", 5, "จำนวนพาดหัว", 2, 8, by_intensity=(3, 5, 7))],
                     inputs=["คำสำคัญในบทพูด"], fallback="ลดจำนวนถ้าไม่มีพื้นที่ว่าง", layout="full", attention=1.8,
                     cost=1.0),
        DoodleBoil("doodle_boil", "Doodle Boil", "เส้นวาดมือ", "overlay", "real",
                   "วงกลม/ขีดเส้นใต้/ลูกศรวาดมือรอบคำที่เน้นในซับ วาดใหม่ทุกเฟรม 1/12 วินาที (boil) ไม่ทับใบหน้า",
                   params=[Param("count", "int", 2, "จำนวนจุด", 1, 4, by_intensity=(1, 2, 3)),
                           Param("boil_fps", "int", 12, "ความถี่ boil", 6, 15),
                           Param("arrows", "bool", True, "ลูกศร"),
                           Param("color", "choice", "white", "สีเส้น", choices=["white", "primary"])],
                   inputs=["ซับไตเติลที่มีคำเน้น"], fallback="—", attention=0.8, cost=1.0),
        GlassyType("glassy_type", "Glassy Type", "ข้อความกระจก", "overlay", "real",
                   "แผงกระจก: เบลอภาพจริงด้านหลังเฉพาะพื้นที่ (boxblur) + ฟิล์มขาวโปร่งแสง + ขอบสะท้อน + เรืองสีแบรนด์ + ข้อความ",
                   inputs=["หัวข้อ/ตัวเลข/สรุปจากบทพูด"], fallback="—", layout="full", attention=1.4, cost=1.2),
        CoverStory("cover_story", "Cover Story", "หน้าปกนิตยสาร", "overlay", "real",
                   "หัวนิตยสาร (ชื่อแบรนด์) อยู่หลังศีรษะเมื่อแยกตัวบุคคลได้, ฉบับ/วันที่จริง, พาดหัวจากบทพูด, cover lines = ประเด็นถัดไปในคลิป",
                   params=[Param("hold", "float", 3.5, "แสดงนาน (วินาที)", 2, 8)],
                   enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "ชื่อแบรนด์", "บทพูด"],
                   fallback="หัวนิตยสารอยู่ด้านหน้าเมื่อแยกตัวบุคคลไม่ได้", layout="full", attention=2.0, cost=2.0),
    ]
