"""Layer-compositing effects that need a person mask: Frame Break, Green Screen, Couch Wall.
Each degrades to a simpler, clean look when the mask is unavailable or fails its quality check."""
import os

from .. import FONTS_DIR
from ..graphics import Script, rrect, text_width, fit_size
from .base import Effect, Param


def _even(v):
    return int(v) // 2 * 2


def _hex(c):
    return "0x" + c.lstrip("#")


def bg_input(cx):
    return ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", str(cx.bg_png)]


def bg_cover(idx, rw, rh, extra=""):
    return (f"[{idx}:v]scale={rw}:{rh}:force_original_aspect_ratio=increase,crop={rw}:{rh},setsar=1"
            f"{(',' + extra) if extra else ''}")


def clip_ass(cx, name, build):
    """Write a clip-local ASS script (times relative to the clip) and return the ass= filter."""
    sc = Script(cx.settings)
    build(sc)
    path = cx.work / f"{name}.ass"
    path.write_text(sc.document(), encoding="utf-8")
    fonts = os.path.relpath(FONTS_DIR, cx.work)
    return f"ass={path.name}:fontsdir={fonts}"


class FrameBreak(Effect):
    def card_rect(self, cx):
        rw, rh = cx.rw, cx.rh
        f = cx.face
        mx = _even(rw * 0.07)
        if f:
            top = f[1] + (f[3] - f[1]) * 0.32   # card edge crosses the forehead: the head breaks out above it
        else:
            top = rh * 0.30
        top = _even(max(rh * 0.12, min(top, rh * 0.5)))
        h = _even(min(rh * 0.68, rh - top - rh * 0.08))
        return mx, top, _even(rw - 2 * mx), h

    def composite(self, p, cx, idx):
        rw, rh = cx.rw, cx.rh
        x, y, w, h = self.card_rect(cx)
        B = max(2, _even(p["border"] * cx.S))
        sh = _even(18 * cx.S)
        col = _hex(cx.settings.get("accent", "#BC0000"))
        g = (bg_cover(idx, rw, rh, "eq=brightness=-0.04") + "[bgi];"
             f"[pres]split[pa][pb];[pa]crop={w}:{h}:{x}:{y}[card];"
             f"[bgi]drawbox=x={x + sh}:y={y + sh}:w={w}:h={h}:color=black@0.55:t=fill[bgs];"
             f"[bgs][card]overlay={x}:{y}[c1];"
             f"[c1]drawbox=x={x - B}:y={y - B}:w={w + 2 * B}:h={h + 2 * B}:color={col}:t={B}[c2];")
        if cx.mask_ok:
            g += (f"[mask]scale={rw}:{rh}:flags=bicubic,format=gray[mk];[pb][mk]alphamerge[fg];"
                  f"[c2][fg]overlay=0:0:format=auto[v]")
        else:   # fallback: framed inset only (no break-out) — clean rather than a bad cut-out
            g += "[pb]nullsink;[c2]null[v]"
        return bg_input(cx), g

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or not f["face"] or f["dur"] < 1.5:
            return None
        if f["role"] == "hook":
            return 0.8, "Hook → ให้ผู้พูดทะลุกรอบเพื่อหยุดนิ้วผู้ชม", {}
        if f["importance"] >= 0.7:
            return 0.45, "ประโยคเด่น → Frame Break เป็นจุดสนใจทางภาพ", {}
        return None


class GreenScreen(Effect):
    def composite(self, p, cx, idx):
        rw, rh = cx.rw, cx.rh
        chroma = cx.settings.get("_chroma") or {}
        use_key = chroma.get("key") and chroma.get("share", 0) > 0.35
        if not use_key and not cx.mask_ok:
            return None   # fallback: keep the original background
        args, inputs = [], 0
        asset = _seg_asset(cx)
        if asset:
            if asset["kind"] == "video":
                args += ["-stream_loop", "-1", "-t", f"{cx.d:.4f}", "-i", asset["path"]]
            else:
                args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", asset["path"]]
        else:
            args += bg_input(cx)
        g = (f"[{idx}:v]scale={_even(rw * 1.08)}:{_even(rh * 1.08)}:force_original_aspect_ratio=increase,"
             f"crop={rw}:{rh}:x='(iw-ow)/2+(iw-ow)/2*sin(t*0.3)':y='(ih-oh)/2',setsar=1,"
             f"eq=brightness=-0.06:saturation=0.9,gblur=sigma={1.5 * cx.S:.2f}[nbg];")
        if use_key:
            g += (f"[pres]chromakey={chroma['key']}:0.13:0.07,despill=type={chroma.get('type', 'green')},"
                  f"format=yuva420p[fg];[fg]split[fg1][fgs];[fgs]alphaextract[mk];")
        else:
            g += (f"[mask]scale={rw}:{rh}:flags=bicubic,format=gray,split[mk][mk2];"
                  f"[pres][mk2]alphamerge,eq=contrast=1.03[fg1];")
        # contact shadow from the matte keeps the subject grounded in the new scene
        sx, sy = _even(14 * cx.S), _even(20 * cx.S)
        g += (f"[mk]gblur=sigma={14 * cx.S:.1f},eq=brightness=-0.25[shm];"
              f"color=c=black:s={rw}x{rh}:d={cx.d:.4f}:r={cx.fps}[blk];[blk][shm]alphamerge[shadow];"
              f"[nbg][shadow]overlay={sx}:{sy}[b2];[b2][fg1]overlay=0:0:format=auto[v]")
        return args, g

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or not f["face"]:
            return None
        if ctx["caps"].get("chroma"):
            return 0.7, "ต้นฉบับเป็นฉากเขียว/น้ำเงิน → Chroma key แล้ววางบนฉากใหม่", {}
        if f["has_asset"] or ctx["genre"] == "promo":
            return 0.45, "มีภาพฉากที่เกี่ยวข้อง → แยกผู้พูดออกมาวางบนฉากใหม่", {}
        return 0.12, "เปลี่ยนฉากหลังเป็นโทนแบรนด์", {}


class CouchWall(Effect):
    def frames(self, cx):
        """Picture frames on the wall behind the speaker (region px)."""
        rw, rh = cx.rw, cx.rh
        f = cx.face or [rw * 0.35, rh * 0.25, rw * 0.65, rh * 0.45]
        fw, fh = _even(rw * 0.3), _even(rh * 0.14)
        y = _even(max(rh * 0.09, f[1] - fh * 0.75))
        return [(_even(rw * 0.035), y, fw, fh), (_even(rw * 0.965 - fw), _even(y + fh * 0.3), fw, fh)]

    def composite(self, p, cx, idx):
        rw, rh = cx.rw, cx.rh
        frames = self.frames(cx)
        f = cx.face
        if f:   # frames that would be mostly hidden by the head carry no text (they stay as depth decoration)
            fx0, fy0, fx1, fy1 = f[0] - (f[2] - f[0]) * 0.35, f[1] - (f[3] - f[1]) * 0.5, f[2] + (f[2] - f[0]) * 0.35, f[3]
            def hidden(r):
                x, y, w, h = r
                ox_ = max(0, min(x + w, fx1) - max(x, fx0))
                oy_ = max(0, min(y + h, fy1) - max(y, fy0))
                return ox_ * oy_ > 0.3 * w * h
        else:
            hidden = lambda r: False
        words = [w for w in (cx.seg.get("highlight") or []) if w.strip()] or _content(cx.seg)[:2]
        assets = [a for a in cx.assets.values() if isinstance(a, dict) and a.get("role") == "broll"
                  and a.get("kind") == "image"][:2]
        args, g, cur = [], "[pres]split[pa][pb];[pa]null[w0];", "w0"
        for k, a in enumerate(assets[: len(frames)]):
            x, y, w, h = frames[k]
            args += ["-loop", "1", "-framerate", "30", "-t", f"{cx.d:.4f}", "-i", a["path"]]
            g += (f"[{idx + k}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"eq=brightness=-0.05:saturation=0.85[as{k}];[{cur}][as{k}]overlay={x}:{y}[w{k + 1}];")
            cur = f"w{k + 1}"
        S = cx.S

        def build(sc):
            for k, (x, y, w, h) in enumerate(frames):
                X, Y, Wd, Hd = x / S, y / S, w / S, h / S   # ASS works in 1080x1920 space
                if cx.rw / S < 1000:   # pip presenter region isn't full frame; skip
                    pass
                sc.shape(0, cx.d, X + 14, Y + 18, rrect(Wd, Hd, 10), fill="#000000", fill_a=0x70, blur=10, layer=0)
                if k >= len(assets):
                    sc.shape(0, cx.d, X, Y, rrect(Wd, Hd, 10), fill="#141010", fill_a=0x18, layer=1)
                    word = words[k] if k < len(words) and not hidden(frames[k]) else ""
                    if word:
                        size = fit_size(word, "Kanit ExtraBold", 64, Wd - 40)
                        sc.atext(0, cx.d, X + Wd / 2, Y + Hd / 2, word, size=size, bord=3, layer=4, glow=False)
                sc.shape(0, cx.d, X, Y, rrect(Wd, Hd, 10), fill="#000000", fill_a=0xFF,
                         border=cx.settings.get("accent", "#BC0000"), bord=6, layer=3)
        g += f"[{cur}]{clip_ass(cx, f'wall_{cx.seg['id']}_{cx.item['ci']}', build)}[wall];"
        if cx.mask_ok:
            g += f"[mask]scale={rw}:{rh}:flags=bicubic,format=gray[mk];[pb][mk]alphamerge[fg];[wall][fg]overlay=0:0:format=auto[v]"
        else:
            g += "[pb]nullsink;[wall]null[v]"
        return args, g

    def eligible(self, f, ctx):
        if f["layout_base"] != "full" or not f["face"] or f["dur"] < 2.0:
            return None
        if ctx["genre"] in ("story", "talking", "review") and len(f["keywords"]) >= 2:
            return 0.4, "เล่าเรื่อง/สัมภาษณ์ → วางกรอบภาพคำสำคัญบนผนังหลังผู้พูด", {}
        return None


def _content(seg):
    from .. import thai
    return thai.content_words([w["w"] for w in seg["words"]])


def _seg_asset(cx):
    b = cx.seg.get("broll") or {}
    if b.get("kind") == "asset" and b.get("asset") in cx.assets:
        return cx.assets[b["asset"]]
    name = cx.seg.get("_fx_asset")
    return cx.assets.get(name) if name else None


def build():
    return [
        FrameBreak("frame_break", "Frame Break", "ทะลุกรอบ", "composite", "real",
                   "แยกตัวบุคคลด้วย MediaPipe แล้วซ้อนชั้น: พื้นหลัง → การ์ดภาพ+เงา+กรอบสีแบรนด์ → ตัวบุคคล (หัว/ไหล่ล้ำออกนอกกรอบ)",
                   params=[Param("border", "float", 10, "ความหนากรอบ", 4, 24, by_intensity=(8, 10, 14))],
                   requires=[], enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "mask ตัวบุคคล"],
                   fallback="กรอบซ้อน (Inset frame) ไม่ทะลุ เมื่อแยกตัวบุคคลไม่ได้หรือ mask ไม่ผ่าน QC",
                   layout="full", attention=1.6, cost=3.0),
        GreenScreen("green_screen", "Green Screen", "เปลี่ยนฉากหลัง", "composite", "real",
                    "ถ้าต้นฉบับเป็นฉากเขียว/น้ำเงิน: Chroma key + despill; ไม่ใช่: Background removal ด้วย mask, วางบนภาพประกอบหรือฉากแบรนด์ + เงาสัมผัส",
                    params=[], enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "ภาพฉากใหม่ (ถ้ามี)"],
                    fallback="คงพื้นหลังเดิม เมื่อไม่มีฉากเขียวและแยกตัวบุคคลไม่ได้", layout="full", attention=1.3,
                    cost=3.0),
        CouchWall("couch_wall", "Couch Wall", "กรอบภาพบนผนังหลังผู้พูด", "composite", "real",
                  "ใช้ฉากจริงของผู้พูด วางกรอบภาพ (ภาพประกอบหรือคำสำคัญ) บนผนัง 'หลัง' ตัวบุคคลด้วย mask — ไม่มีการสร้างโซฟา/ฉากใหม่ด้วย AI",
                  params=[], enhanced_by=["segmentation"], inputs=["ภาพผู้พูด", "ภาพประกอบ (ถ้ามี)", "คำสำคัญ"],
                  fallback="วางกรอบด้านหน้า (ไม่อยู่หลังตัวบุคคล) เมื่อแยกตัวบุคคลไม่ได้", layout="full", attention=1.2,
                  cost=3.0),
    ]
