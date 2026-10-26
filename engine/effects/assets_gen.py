"""Procedural image assets for effects (Pillow): phone frame, simulated phone screen, paper-cut layers."""
import hashlib
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import FONTS_DIR, thai


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _font(name, size):
    return ImageFont.truetype(str(FONTS_DIR / name), size, layout_engine=ImageFont.Layout.RAQM)


def _key(*parts):
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


def phone_frame(cache, accent, w=420, h=860):
    """RGBA phone body with transparent screen hole + baked soft shadow. Returns (path, screen_rect, size)."""
    path = Path(cache) / f"phone_{_key(accent, w, h, 3)}.png"
    m = int(w * 0.12)
    bez = int(w * 0.04)
    screen = (m + bez, m + bez, w - 2 * bez, h - 2 * bez)
    if path.exists():
        return path, screen, (w + 2 * m, h + 2 * m)
    W, H = w + 2 * m, h + 2 * m
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((m + 10, m + 26, m + w + 10, m + h + 26), int(w * 0.13), fill=(0, 0, 0, 170))
    img = shadow.filter(ImageFilter.GaussianBlur(m * 0.45))
    d = ImageDraw.Draw(img)
    r = int(w * 0.13)
    d.rounded_rectangle((m, m, m + w, m + h), r, fill=(18, 18, 20, 255), outline=_rgb(accent) + (255,), width=3)
    d.rounded_rectangle((m + 4, m + 4, m + w - 4, m + h - 4), r - 4, outline=(70, 70, 74, 255), width=2)
    # side buttons
    d.rounded_rectangle((m + w - 1, m + int(h * 0.2), m + w + 4, m + int(h * 0.3)), 2, fill=(40, 40, 44, 255))
    d.rounded_rectangle((m - 4, m + int(h * 0.18), m + 1, m + int(h * 0.24)), 2, fill=(40, 40, 44, 255))
    # screen hole
    hole = Image.new("L", (W, H), 0)
    ImageDraw.Draw(hole).rounded_rectangle((screen[0], screen[1], screen[0] + screen[2], screen[1] + screen[3]),
                                           r - bez, fill=255)
    a = np.array(img)
    a[..., 3] = np.where(np.array(hole) > 0, 0, a[..., 3])
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    # dynamic island
    iw = int(w * 0.28)
    d.rounded_rectangle((m + (w - iw) // 2, m + bez + 12, m + (w + iw) // 2, m + bez + 12 + int(w * 0.075)), 20,
                        fill=(5, 5, 6, 255))
    img.save(path)
    return path, screen, (W, H)


def sim_screen(cache, w, h, title, lines, keywords, accent, second):
    """A clearly-labelled *simulated* screen showing only words from the transcript."""
    path = Path(cache) / f"screen_{_key(w, h, title, lines, keywords, accent, 2)}.png"
    if path.exists():
        return path
    img = Image.new("RGB", (w, h), (16, 15, 15))
    d = ImageDraw.Draw(img)
    A, B = _rgb(accent), _rgb(second)
    d.rectangle((0, 0, w, int(h * 0.12)), fill=A)
    d.ellipse((int(w * 0.06), int(h * 0.035), int(w * 0.06) + int(h * 0.05), int(h * 0.085)), fill=B)
    d.text((int(w * 0.18), int(h * 0.06)), "ภาพจำลองหน้าจอ", font=_font("Kanit-SemiBold.ttf", int(h * 0.032)),
           fill=(255, 255, 255), anchor="lm")
    y = int(h * 0.17)
    f_title = _font("Kanit-ExtraBold.ttf", int(h * 0.05))
    for ln in _wrap(title, f_title, w * 0.84)[:3]:
        d.text((int(w * 0.08), y), ln, font=f_title, fill=(255, 255, 255))
        y += int(h * 0.065)
    y += int(h * 0.02)
    f_body = _font("Kanit-Regular.ttf", int(h * 0.03))
    for line in lines[:4]:
        for ln in _wrap(line, f_body, w * 0.84)[:2]:
            d.text((int(w * 0.08), y), ln, font=f_body, fill=(200, 196, 192))
            y += int(h * 0.045)
    y += int(h * 0.03)
    f_chip = _font("Kanit-SemiBold.ttf", int(h * 0.03))
    x = int(w * 0.08)
    for kw in keywords[:4]:
        tw = d.textlength(kw, font=f_chip)
        if x + tw + 40 > w * 0.92:
            x = int(w * 0.08)
            y += int(h * 0.06)
        d.rounded_rectangle((x, y, x + tw + 32, y + int(h * 0.05)), 20, outline=A, width=3)
        d.text((x + 16, y + int(h * 0.025)), kw, font=f_chip, fill=(255, 255, 255), anchor="lm")
        x += int(tw + 48)
    img.save(path)
    return path


def _wrap(text, font, maxw):
    toks = thai.tokenize(text)
    lines, cur = [], ""
    for t in toks:
        cand = cur + t
        if cur and font.getlength(cand.strip()) > maxw:
            lines.append(cur.strip())
            cur = t.lstrip()
        else:
            cur = cand
    if cur.strip():
        lines.append(cur.strip())
    return lines


def paper_layers(cache, w, h, accent, second, asset_path=None, keywords=(), seed=1):
    """Layered paper-cut collage. Returns [(png_path, depth)], back to front. depth drives parallax/jitter."""
    key = _key(w, h, accent, second, str(asset_path), tuple(keywords), seed, 4)
    out_dir = Path(cache) / f"paper_{key}"
    done = out_dir / "done"
    if done.exists():
        return [(p, float(p.stem.split("_")[2])) for p in sorted(out_dir.glob("layer_*.png"))]
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    A, B = np.array(_rgb(accent), float), np.array(_rgb(second), float)
    M = int(max(w, h) * 0.06)   # margin so jittering layers never show edges
    Wm, Hm = w + 2 * M, h + 2 * M
    paper = np.array([238, 230, 218], float)
    dark = np.array([28, 24, 24], float)
    palette = [dark, A * 0.55 + dark * 0.45, A, A * 0.5 + paper * 0.5, paper]

    def texture(rgb_mask, color):
        noise = rng.normal(0, 7, (Hm, Wm, 1))
        img = np.clip(np.ones((Hm, Wm, 3)) * color + noise, 0, 255).astype(np.uint8)
        rgba = np.dstack([img, (rgb_mask * 255).astype(np.uint8)])
        return Image.fromarray(rgba, "RGBA")

    def with_shadow(layer):
        a = layer.split()[3]
        sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        sh.putalpha(a.point(lambda v: int(v * 0.55)).filter(ImageFilter.GaussianBlur(M * 0.12)))
        base = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        base.alpha_composite(sh, (int(M * 0.06), int(M * 0.1)))
        base.alpha_composite(layer)
        return base

    def rough(mask):
        im = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.2))
        return (np.array(im) > 127).astype(float)

    layers = []
    bg = texture(np.ones((Hm, Wm)), dark * 0.9 + A * 0.1)
    layers.append((bg, 0.0))
    if asset_path:
        src = Image.open(asset_path).convert("L")
        src = src.resize((Wm, Hm)) if abs(src.width / src.height - Wm / Hm) < 0.05 else _cover(src, Wm, Hm)
        lum = np.array(src.filter(ImageFilter.GaussianBlur(3)), float)
        qs = np.quantile(lum, [0.3, 0.55, 0.78])
        for k, q in enumerate(qs):
            mask = rough((lum >= q).astype(float))
            layers.append((with_shadow(texture(mask, palette[k + 1])), 0.3 + 0.25 * k))
    else:
        x = np.arange(Wm)
        text = " ".join(keywords)
        for k in range(3):   # rolling hills / waves, back to front
            base_y = Hm * (0.52 + 0.13 * k)
            amp = Hm * (0.05 + 0.02 * k)
            ph = rng.uniform(0, 6.28)
            freq = 2 * math.pi / (Wm * rng.uniform(0.5, 0.9))
            ys = base_y + amp * np.sin(x * freq + ph) + amp * 0.35 * np.sin(x * freq * 2.7 + ph * 1.3)
            if any(t in text for t in ("ทะเล", "น้ำ", "ทะเลสาบ", "แม่น้ำ")) and k == 2:
                ys = base_y + amp * 0.5 * np.sin(x * freq * 4 + ph)
            mask = (np.arange(Hm)[:, None] >= ys[None, :]).astype(float)
            layers.append((with_shadow(texture(rough(mask), palette[k + 1])), 0.35 + 0.2 * k))
        # moon/sun in the secondary colour
        cx_, cy_, r = Wm * rng.uniform(0.6, 0.8), Hm * 0.26, Hm * 0.09
        yy, xx = np.mgrid[0:Hm, 0:Wm]
        moon = (((xx - cx_) ** 2 + (yy - cy_) ** 2) < r * r).astype(float)
        layers.insert(1, (with_shadow(texture(moon, B)), 0.15))
        if any(t in text for t in ("บ้าน", "หมู่บ้าน", "กระท่อม")):
            hm = np.zeros((Hm, Wm))
            for hx in (0.22, 0.38):
                x0, y0, s = int(Wm * hx), int(Hm * 0.6), int(Hm * 0.1)
                hm[y0:y0 + s, x0:x0 + s] = 1
                for i in range(s // 2 + 1):
                    hm[y0 - i, x0 + i:x0 + s - i] = 1
            layers.append((with_shadow(texture(rough(hm), dark)), 0.6))
        if any(t in text for t in ("ป่า", "ต้นไม้")):
            tm = np.zeros((Hm, Wm))
            for tx in rng.uniform(0.05, 0.95, 6):
                x0, y0, s = int(Wm * tx), int(Hm * 0.62), int(Hm * 0.16)
                for i in range(s):
                    half = int(i * 0.35)
                    tm[y0 + i - s, max(0, x0 - half):x0 + half] = 1
            layers.append((with_shadow(texture(rough(tm), dark * 0.8 + A * 0.2)), 0.55))
    paths = []
    for k, (img, depth) in enumerate(layers):
        p = out_dir / f"layer_{k:02d}_{depth:.2f}.png"
        img.save(p)
        paths.append((p, depth))
    done.write_text("ok")
    return paths


def _cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))
