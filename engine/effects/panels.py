"""Information panels: UI World, Chart Grow, Checklist (motion graphics, data only from the transcript),
Phone Mockup and Paper Cut (procedural media panels)."""
import re

from .. import thai
from ..graphics import SAFE, circle, esc, fit_size, rrect, text_width, wrap
from . import assets_gen as AG
from .base import Effect, Param

TECH_CUES = ["แอป", "ระบบ", "ข้อมูล", "ยอด", "ธุรกิจ", "ออนไลน์", "เว็บไซต์", "เทคโนโลยี", "AI", "การตลาด", "ลูกค้า",
             "แพลตฟอร์ม", "โฆษณา", "แคมเปญ", "รายได้", "กำไร", "สถิติ", "ผู้ใช้", "ดิจิทัล", "ข้อมูล", "เปอร์เซ็นต์"]
PHONE_CUES = ["แอป", "เว็บไซต์", "โซเชียล", "TikTok", "ติ๊กต็อก", "เฟซบุ๊ก", "ไลน์", "มือถือ", "โพสต์", "รีวิว", "ผลงาน",
              "หน้าจอ", "ยูทูบ", "YouTube", "Instagram", "อินสตาแกรม", "เพจ"]
STORY_CUES = ["เมื่อ", "ตำนาน", "เรื่องเล่า", "ประวัติ", "สมัย", "นิทาน", "กาลครั้งหนึ่ง", "อดีต", "โบราณ"]
TIP_CUES = ["ต้อง", "ควร", "อย่า", "ห้าม", "เคล็ดลับ", "ข้อควรระวัง", "วิธี", "ข้อแรก", "ขั้นแรก", "อย่างแรก"]


def panel_rect(ox):
    return (0, 0, 1080, 960) if ox.layout in ("pip", "split") else (0, 0, 1080, 1920)


class UIWorld(Effect):
    def overlay(self, sc, p, ox):
        px, py, pw, ph = panel_rect(ox)
        t0, t1 = ox.t0 + 0.05, ox.t1
        fade = "\\fad(200,150)"
        x, y = 50, py + SAFE["top"] + 10
        w, h = 980, min(ph - SAFE["top"] - 50, 760)
        # window
        sc.shape(t0, t1, x + 12, y + 16, rrect(w, h, 26), fill="#000000", fill_a=0x60, blur=14, layer=1, extra=fade)
        sc.shape(t0, t1, x, y, rrect(w, h, 26), fill="#121111", fill_a=0x10, border=sc.primary, bord=2, layer=2,
                 extra=fade + "\\fscx94\\fscy94\\t(0,220,\\fscx100\\fscy100)")
        sc.shape(t0, t1, x, y, rrect(w, 64, 26), fill="#1E1C1C", layer=3, extra=fade)
        for k, c in enumerate((sc.primary, sc.second, "#DDDDDD")):
            sc.shape(t0, t1, x + 30 + k * 34, y + 22, circle(20), fill=c, layer=4, extra=fade)
        brand = ox.settings.get("brand_name") or "Dashboard"
        sc.text(t0, t1, x + w / 2, y + 32, brand, size=30, family="Kanit SemiBold", color="#BBBBBB", bord=0, shad=0,
                layer=4, extra=fade)
        # sidebar
        for k in range(5):
            sc.shape(t0 + 0.05 * k, t1, x + 26, y + 100 + k * 92, rrect(56, 56, 14),
                     fill=sc.primary if k == 0 else "#2A2727", layer=4, extra=fade)
        cx0, cw = x + 112, w - 140
        # "search bar": the key clause types out word by word as it is spoken
        bar_y = y + 92
        sc.shape(t0, t1, cx0, bar_y, rrect(cw, 76, 38), fill="#1C1A1A", border="#3A3434", bord=2, layer=4, extra=fade)
        sc.shape(t0, t1, cx0 + 24, bar_y + 24, circle(28), fill="#000000", fill_a=0xFF, border=sc.second, bord=3,
                 layer=5, extra=fade)
        typed = ""
        words = [w_ for w_ in ox.seg["words"] if w_["w"] != " " or typed]
        for i, w_ in enumerate(ox.seg["words"]):
            if w_["w"] == " " and not typed:
                continue
            nxt = typed + w_["w"]
            if text_width(nxt, "Kanit SemiBold", 36) > cw - 110:
                break
            typed = nxt
            if w_["s"] is None:
                continue
            a = max(t0, ox.word_out(i))
            sc.text(a, t1, cx0 + 72, bar_y + 38, typed, size=36, family="Kanit SemiBold", an=4, bord=0, shad=0,
                    layer=6)
        # KPI tiles: only numbers that were actually said
        nums = ox.feat.get("numbers") or []
        tiles = [(n[1] + (" " + n[2] if n[2] else ""), thai.short_title(n[3], 14) or "ตัวเลขจากบทพูด", n[0])
                 for n in nums[:3]]
        if not tiles:
            tiles = [(k_, "คำสำคัญ", None) for k_ in (ox.feat.get("keywords") or [])[:3]]
        n = max(1, len(tiles))
        tw_ = (cw - 24 * (n - 1)) / n
        ty = bar_y + 110
        for k, (val, cap, wi) in enumerate(tiles):
            tx = cx0 + k * (tw_ + 24)
            a = max(t0, ox.word_out(wi) - 0.2) if wi is not None else t0 + 0.2 + 0.15 * k
            sc.shape(a, t1, tx, ty, rrect(tw_, 230, 22), fill="#1A1818", border=sc.primary, bord=2, layer=4,
                     extra="\\fad(180,150)\\fscy80\\t(0,200,\\fscy100)")
            vs = fit_size(val, "Kanit ExtraBold", 84, tw_ - 40)
            sc.atext(a, t1, tx + tw_ / 2, ty + 95, val, size=vs, bord=3, layer=6, glow=False, extra="\\fad(180,150)")
            cs = fit_size(cap, "Kanit SemiBold", 32, tw_ - 30)
            sc.text(a, t1, tx + tw_ / 2, ty + 180, cap, size=cs, family="Kanit SemiBold", color="#CCCCCC", bord=0,
                    shad=0, layer=6, extra="\\fad(180,150)")
        # neutral skeleton rows (decorative, carry no data)
        ry = ty + 270
        for k in range(3):
            if ry + k * 56 + 26 > y + h - 30:
                break
            sc.shape(t0 + 0.3, t1, cx0, ry + k * 56, rrect(cw * (0.9 - 0.18 * k), 22, 11), fill="#2A2626", layer=4,
                     extra=fade)
        sc.label(t0, t1, "ข้อมูลจากบทพูด", x=60, y=y + h + 16 if y + h + 70 < py + ph else 180)

    def eligible(self, f, ctx):
        tech = sum(1 for c in TECH_CUES if c in f["text"])
        if f["numbers"] and (tech or ctx["genre"] in ("news", "promo")):
            return 0.75, "มีตัวเลขในบริบทธุรกิจ/ข้อมูล → แสดงเป็น Dashboard (ตัวเลขตามที่พูด)", {}
        if tech >= 2:
            return 0.55, "พูดถึงเทคโนโลยี/ธุรกิจ → UI World", {}
        return None


class ChartGrow(Effect):
    def overlay(self, sc, p, ox):
        series = ox.feat.get("chart_series") or []
        if len(series) < 2:   # not enough real data for a chart: never invent values, show what was said
            nums = ox.feat.get("numbers") or []
            if nums:
                i, raw, unit, before = nums[0]
                sc.stat(ox.t0 + 0.05, ox.t1, raw, unit, thai.short_title(before, 18), "ตัวเลขจากคำพูดในคลิป",
                        panel_rect(ox), t_spoken=ox.word_out(i) - 0.15)
            if ox.report is not None:
                ox.report.append({"seg": ox.seg["id"], "effect": "chart_grow", "status": "fallback",
                                  "msg": "ตัวเลขในประโยคไม่ถึง 2 ค่าหน่วยเดียวกัน → แสดงการ์ดตัวเลขเดี่ยวแทนกราฟ"})
            return
        px, py, pw, ph = panel_rect(ox)
        t0, t1 = ox.t0 + 0.05, ox.t1
        x0, y_base = 150, py + ph - 150
        top = py + SAFE["top"] + 120
        chart_h = y_base - top
        vals = [s["value"] for s in series]
        vmax = max(vals) or 1
        n = len(series)
        slot = (pw - 260) / n
        bw = min(170, slot * 0.6)
        fade = "\\fad(150,150)"
        sc.shape(t0, t1, x0 - 10, y_base, rrect(pw - 240, 5, 2), fill="#DDDDDD", layer=3, extra=fade)
        unit = series[0]["unit"]
        sc.text(t0, t1, 80, top - 70, f"หน่วย: {unit}" if unit else "ค่าตามที่กล่าวในคลิป", size=34, family="Kanit SemiBold",
                an=4, color="#CCCCCC", bord=0, shad=0, layer=4, extra=fade)
        for k, s in enumerate(series):
            bh = max(8, chart_h * s["value"] / vmax)
            bx = x0 + k * slot + (slot - bw) / 2
            a = max(t0 + 0.1 * k, ox.word_out(s["word_index"]) - 0.15)
            grow = f"\\clip({bx - 20:.0f},{y_base:.0f},{bx + bw + 20:.0f},{y_base:.0f})" \
                   f"\\t(0,600,\\clip({bx - 20:.0f},{y_base - bh - 10:.0f},{bx + bw + 20:.0f},{y_base:.0f}))"
            col = sc.primary if k == n - 1 else "#7A1010"
            sc.shape(a, t1, bx, y_base - bh, rrect(bw, bh, 10), fill=col, layer=4, extra=grow + "\\fad(0,150)")
            sc.shape(a, t1, bx, y_base - bh, rrect(bw, bh, 10), fill="#000000", fill_a=0xFF, border=sc.primary,
                     bord=6, border_a=0xA0, blur=10, layer=3, extra=grow + "\\fad(0,150)")
            lab = s["raw"]
            ls = fit_size(lab, "Kanit ExtraBold", 62, slot - 10)
            sc.text(a + 0.45, t1, bx + bw / 2, y_base - bh - 46, lab, size=ls, color="#FFFFFF", bord=3, shad=0,
                    layer=6, extra="\\fad(150,150)")
            cap = s["label"]
            cs = fit_size(cap, "Kanit SemiBold", 32, slot - 10)
            sc.text(a, t1, bx + bw / 2, y_base + 46, cap, size=cs, family="Kanit SemiBold", color="#DDDDDD", bord=0,
                    shad=0, layer=6, extra=fade)
        sc.label(t0, t1, "กราฟจากตัวเลขในบทพูด", x=60, y=py + SAFE["top"] + 10)

    def eligible(self, f, ctx):
        if len(f.get("chart_series") or []) >= 2:
            return 0.9, f"มีตัวเลข {len(f['chart_series'])} ค่าหน่วยเดียวกัน → กราฟแท่งเติบโตตามลำดับที่พูด", {}
        return None


class Checklist(Effect):
    def overlay(self, sc, p, ox):
        items = ox.feat.get("checklist") or []
        if not items:
            return
        px, py, pw, ph = panel_rect(ox)
        t0, t1 = ox.t0 + 0.05, ox.t1
        per_page = int(p["per_page"])
        pages = [items[i:i + per_page] for i in range(0, len(items), per_page)]
        row_h = min(170, (ph - SAFE["top"] - 100) / per_page)
        for pi, page in enumerate(pages):
            p_start = max(t0, ox.word_out(page[0]["word_index"]) - 0.3) if pi else t0
            p_end = (max(t0, ox.word_out(pages[pi + 1][0]["word_index"]) - 0.3) if pi + 1 < len(pages) else t1)
            top = py + max(SAFE["top"] + 20, (ph - row_h * len(page)) / 2 + 20)
            for k, it in enumerate(page):
                y = top + k * row_h
                ta = min(max(p_start, ox.word_out(it["word_index"]) - 0.1), p_end - 0.2)
                sc.shape(p_start, p_end, 80, y, rrect(920, row_h - 26, 20), fill="#141212", fill_a=0x10,
                         border="#3A3434", bord=2, layer=2, extra="\\fad(150,120)")
                bx, by, bs = 112, y + (row_h - 26) / 2 - 30, 60
                sc.shape(p_start, p_end, bx, by, rrect(bs, bs, 12), fill="#000000", fill_a=0xFF, border="#888888",
                         bord=3, layer=3, extra="\\fad(150,120)")
                # the check mark draws itself when the item is spoken
                sc.shape(ta, p_end, bx, by, rrect(bs, bs, 12), fill=sc.primary, layer=4,
                         extra="\\fad(80,120)\\fscx60\\fscy60\\t(0,120,\\fscx100\\fscy100)")
                tick = "m 14 32 l 26 44 l 48 18"
                sc.ev(ta, p_end, "{\\an7\\pos(%d,%d)\\p1\\bord5\\shad0\\1a&HFF&\\3c&HFFFFFF&\\clip(%d,0,%d,1920)"
                      "\\t(0,260,\\clip(%d,0,%d,1920))}%s{\\p0}" % (bx, by, bx, bx, bx, bx + bs, tick), layer=5)
                label = it["text"]
                ls = fit_size(label, "Kanit SemiBold", 46, 920 - 150)
                if text_width(label, "Kanit SemiBold", ls) > 770:
                    label = wrap(label, "Kanit SemiBold", ls, 770, 1)[0]
                sc.text(p_start, p_end, 200, y + (row_h - 26) / 2, label, size=ls, family="Kanit SemiBold", an=4,
                        color="#9A9090", bord=0, shad=0, layer=5, extra="\\fad(150,120)")
                sc.text(ta, p_end, 200, y + (row_h - 26) / 2, label, size=ls, family="Kanit SemiBold", an=4,
                        color="#FFFFFF", bord=0, shad=0, layer=6, extra="\\fad(120,120)")

    def eligible(self, f, ctx):
        if len(f.get("checklist") or []) >= 2:
            tip = any(c in f["text"] for c in TIP_CUES)
            return (0.85 if tip or f["role"] == "steps" else 0.5,
                    f"มีรายการ {len(f['checklist'])} ข้อ → Checklist ติ๊กถูกตามจังหวะพูด", {})
        return None


class PhoneMockup(Effect):
    def panel(self, p, cx, idx, pw, ph):
        S = cx.S
        fh = int(ph * 0.86) // 2 * 2
        fw = int(fh * 0.49) // 2 * 2
        frame, scr, (FW, FH) = AG.phone_frame(cx.cache, cx.settings.get("accent", "#BC0000"), fw, fh)
        assets = _media_assets(cx)
        args = ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", str(cx.bg_png)]
        if assets:
            a = assets[0]
            if a["kind"] == "video":
                args += ["-stream_loop", "-1", "-t", f"{cx.d:.4f}", "-i", a["path"]]
            else:
                args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", a["path"]]
        else:
            title = cx.seg.get("title") or thai.key_clause(cx.seg["text"], cx.seg.get("highlight") or [], 22)
            img = AG.sim_screen(cx.cache, scr[2], scr[3], title, [cx.seg["text"]], cx.seg.get("highlight") or [],
                                cx.settings.get("accent", "#BC0000"), cx.settings.get("accent2", "#A8CE20"))
            args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", str(img)]
        args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", str(frame)]
        x0 = (pw - FW) // 2
        y0 = (ph - FH) // 2 + int(20 * S)
        amp = p["float"] * S
        fl = f"{amp:.1f}*sin(t*1.7)"
        g = (f"[{idx}:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1[pbg];"
             f"[{idx + 1}:v]scale={scr[2]}:{scr[3]}:force_original_aspect_ratio=increase,crop={scr[2]}:{scr[3]},setsar=1[scr];"
             f"[pbg][scr]overlay=x={x0 + scr[0]}:y='{y0 + scr[1]}+{fl}'[p1];"
             f"[p1][{idx + 2}:v]overlay=x={x0}:y='{y0}+{fl}'[panel]")
        cx.seg.setdefault("_runtime", {})["phone_simulated"] = not assets
        return args, g

    def overlay(self, sc, p, ox):
        if ox.rt.get("phone_simulated", True):
            sc.label(ox.t0 + 0.05, ox.t1, "ภาพจำลองหน้าจอ", x=60, y=180)
        else:
            sc.label(ox.t0 + 0.05, ox.t1, "ภาพประกอบในกรอบมือถือ", x=60, y=180)

    def eligible(self, f, ctx):
        cue = any(c in f["text"] for c in PHONE_CUES)
        if cue and f["has_asset"]:
            return 0.85, "พูดถึงแอป/โซเชียล และมีภาพหน้าจอ → แสดงในกรอบมือถือ", {}
        if cue:
            return 0.6, "พูดถึงแอป/โซเชียล → กรอบมือถือ (หน้าจอจำลองจากคำพูด มีป้ายกำกับ)", {}
        if f["has_asset"] and ctx["genre"] in ("review", "promo"):
            return 0.5, "รีวิว/โปรโมต → นำภาพผลงานไปแสดงในกรอบมือถือ", {}
        return None


class PaperCut(Effect):
    def panel(self, p, cx, idx, pw, ph):
        assets = [a for a in _media_assets(cx) if a["kind"] == "image"]
        kws = (cx.seg.get("highlight") or []) + thai.content_words(thai.tokenize(cx.seg["text"]))[:6]
        layers = AG.paper_layers(cx.cache, pw, ph, cx.settings.get("accent", "#BC0000"),
                                 cx.settings.get("accent2", "#A8CE20"), assets[0]["path"] if assets else None,
                                 kws, seed=sum(map(ord, cx.seg["id"])))
        args, g = [], ""
        M = int(max(pw, ph) * 0.06)
        fps_sm = p["stop_fps"]
        cur = None
        for k, (path, depth) in enumerate(layers):
            args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", str(path)]
            j = p["jitter"] * cx.S * (0.5 + depth)
            drift = 14 * cx.S * depth
            # stop-motion: positions only change fps_sm times per second
            st = f"floor((t+{cx.t_off:.3f})*{fps_sm})"
            x = f"-{M}+{j:.2f}*sin({st}*{1.7 + k:.2f})-{drift:.2f}*(t+{cx.t_off:.3f})/4"
            y = f"-{M}+{j:.2f}*cos({st}*{2.3 + k:.2f})"
            if cur is None:
                g += f"[{idx + k}:v]crop={pw}:{ph}:{M}:{M},setsar=1[pc0];"
                cur = "pc0"
            else:
                g += f"[{cur}][{idx + k}:v]overlay=x='{x}':y='{y}'[pc{k}];"
                cur = f"pc{k}"
        g += f"[{cur}]null[panel]"
        cx.seg.setdefault("_runtime", {})["paper_from_asset"] = bool(assets)
        return args, g

    def overlay(self, sc, p, ox):
        sc.label(ox.t0 + 0.05, ox.t1, "ภาพประกอบแบบกระดาษตัด", x=60, y=180)

    def eligible(self, f, ctx):
        story = any(c in f["text"] for c in STORY_CUES) or f["mystery"]
        if story and ctx["genre"] in ("story",):
            return 0.65, "ช่วงเล่าเรื่อง/ประวัติ → ภาพประกอบกระดาษตัดซ้อนชั้นแบบ Stop motion", {}
        if story:
            return 0.4, "บรรยายเหตุการณ์ → Paper cut แทนภาพจริงที่ไม่มี", {}
        return None


def _media_assets(cx):
    out = []
    b = cx.seg.get("broll") or {}
    if b.get("kind") == "asset" and b.get("asset") in cx.assets:
        out.append(cx.assets[b["asset"]])
    name = cx.seg.get("_fx_asset")
    if name and name in cx.assets and cx.assets[name] not in out:
        out.append(cx.assets[name])
    return [a for a in out if a.get("kind") in ("image", "video")]


def build():
    return [
        UIWorld("ui_world", "UI World", "โลกกราฟิก UI", "panel", "real",
                "Dashboard วาดด้วย libass: แถบค้นหาพิมพ์ตามเสียงพูด, การ์ด KPI เฉพาะตัวเลขที่พูดจริง, ไม่มีกราฟ/ค่าที่แต่งขึ้น",
                inputs=["บทพูด", "ตัวเลขในบทพูด"], fallback="ใช้คำสำคัญแทนเมื่อไม่มีตัวเลข", layout="pip", attention=2.0,
                cost=1.0),
        ChartGrow("chart_grow", "Chart Grow", "กราฟเติบโต", "panel", "real",
                  "กราฟแท่งจากตัวเลข ≥2 ค่าหน่วยเดียวกันในบทพูด แท่งขึ้นตามจังหวะที่พูด แสดงหน่วยและที่มา",
                  inputs=["ตัวเลขในบทพูด (ต้องมีอย่างน้อย 2 ค่า หน่วยเดียวกัน)"],
                  fallback="ไม่ถูกเลือกถ้าข้อมูลไม่พอ (ใช้การ์ดตัวเลขเดี่ยวแทน) — ไม่แต่งตัวเลข", layout="pip",
                  attention=2.0, cost=1.0),
        Checklist("checklist", "Checklist", "เช็กลิสต์", "panel", "real",
                  "รายการจากบทพูด ติ๊กถูกทีละข้อเมื่อพูดถึง แบ่งหน้าถ้าเกินจำนวนต่อจอ",
                  params=[Param("per_page", "int", 4, "จำนวนข้อต่อหน้า", 2, 5)],
                  inputs=["ขั้นตอน/ข้อแนะนำในบทพูด"], fallback="—", layout="pip", attention=1.8, cost=1.0),
        PhoneMockup("phone_mockup", "Phone Mockup", "กรอบสมาร์ตโฟน", "panel", "real",
                    "กรอบมือถือสร้างด้วย Pillow + เงา ลอยขึ้นลง แสดงภาพ/วิดีโอที่อัปโหลด; ไม่มีไฟล์ → หน้าจอจำลองจากคำพูด พร้อมป้าย 'ภาพจำลองหน้าจอ'",
                    params=[Param("float", "float", 14, "ระยะลอย", 0, 40, by_intensity=(8, 14, 22))],
                    inputs=["ภาพหน้าจอ/วิดีโอ (ถ้ามี)"], fallback="หน้าจอจำลองที่มีป้ายกำกับ", layout="pip",
                    attention=1.6, cost=1.2),
        PaperCut("paper_cut", "Paper Cut", "กระดาษตัด", "panel", "real",
                 "Pillow สร้างชั้นกระดาษ (จากภาพที่อัปโหลด หรือฉากจากคำสำคัญ) + เงา + เท็กซ์เจอร์ ขยับแบบ Stop motion 8 fps",
                 params=[Param("jitter", "float", 3, "การสั่นของชั้น", 0, 8, by_intensity=(2, 3, 5)),
                         Param("stop_fps", "int", 8, "เฟรม stop motion/วินาที", 4, 12)],
                 enhanced_by=["ai_image"], inputs=["ภาพประกอบ (ถ้ามี)", "คำสำคัญ"],
                 fallback="ฉากกระดาษสร้างจากคำสำคัญ เมื่อไม่มีภาพและไม่มี AI image", layout="pip", attention=1.5,
                 cost=1.3),
    ]
