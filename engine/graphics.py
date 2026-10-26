"""Motion graphics and subtitles as an ASS script (rendered by libass inside FFmpeg).

All coordinates are in a 1080x1920 canvas; libass scales to the output size.
"""
from functools import lru_cache

from PIL import ImageFont

from . import FONTS_DIR, thai

W, H = 1080, 1920
SAFE = {"top": 150, "bottom": 1500, "left": 70, "right": 1010}  # TikTok/Reels/Shorts UI-safe area
FONT_FILES = {"Kanit ExtraBold": "Kanit-ExtraBold.ttf", "Kanit SemiBold": "Kanit-SemiBold.ttf", "Kanit": "Kanit-Regular.ttf",
              "Prompt Bold": "Prompt-Bold.ttf", "Chakra Petch Bold": "ChakraPetch-Bold.ttf",
              "Mitr SemiBold": "Mitr-SemiBold.ttf"}
SUBTITLE_FONTS = ["Kanit ExtraBold", "Kanit SemiBold", "Prompt Bold", "Chakra Petch Bold", "Mitr SemiBold"]


def ass_color(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&".upper().replace("&H", "&H", 1)


def luminance(hex_rgb):
    h = hex_rgb.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ts(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def esc(s):
    return s.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ")


@lru_cache(maxsize=64)
def _font(family, ass_size):
    """PIL font whose rendered size matches libass at a given ASS \\fs (libass scales by ascent+descent)."""
    path = FONTS_DIR / FONT_FILES.get(family, "Kanit-ExtraBold.ttf")
    ref = ImageFont.truetype(str(path), 100)
    asc, desc = ref.getmetrics()
    em = max(4, int(round(ass_size * 100 / (asc + desc))))
    return ImageFont.truetype(str(path), em, layout_engine=ImageFont.Layout.RAQM)


def text_width(text, family="Kanit ExtraBold", size=78):
    return _font(family, size).getlength(text)


def fit_size(text, family, size, max_w, min_size=34):
    while size > min_size and text_width(text, family, size) > max_w:
        size -= 2
    return size


def wrap(text, family, size, max_w, max_lines=3):
    """Wrap Thai text at word boundaries to fit max_w px."""
    toks = thai.tokenize(text)
    lines, cur = [], ""
    for t in toks:
        cand = cur + t
        if cur and text_width(cand.strip(), family, size) > max_w:
            lines.append(cur.strip())
            cur = t.lstrip()
        else:
            cur = cand
    if cur.strip():
        lines.append(cur.strip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, len(lines[-1]) - 2)] + "…"
    return lines


def rrect(w, h, r):
    r = min(r, w / 2, h / 2)
    k = r * 0.45
    return (f"m {r:.0f} 0 l {w - r:.0f} 0 b {w - k:.0f} 0 {w:.0f} {k:.0f} {w:.0f} {r:.0f} "
            f"l {w:.0f} {h - r:.0f} b {w:.0f} {h - k:.0f} {w - k:.0f} {h:.0f} {w - r:.0f} {h:.0f} "
            f"l {r:.0f} {h:.0f} b {k:.0f} {h:.0f} 0 {h - k:.0f} 0 {h - r:.0f} l 0 {r:.0f} b 0 {k:.0f} {k:.0f} 0 {r:.0f} 0")


def circle(d):
    r = d / 2
    k = r * 0.552
    return (f"m {r:.0f} 0 b {r + k:.0f} 0 {d:.0f} {r - k:.0f} {d:.0f} {r:.0f} b {d:.0f} {r + k:.0f} {r + k:.0f} {d:.0f} {r:.0f} {d:.0f} "
            f"b {r - k:.0f} {d:.0f} 0 {r + k:.0f} 0 {r:.0f} b 0 {r - k:.0f} {r - k:.0f} 0 {r:.0f} 0")


class Script:
    def __init__(self, settings):
        self.st = settings
        # colour roles: primary = brand colour (borders, cards, highlighted words, glow);
        # second = small pops (timeline dot, VS badge, title-card dot), like the dot in a logo
        self.primary = settings.get("accent", "#BC0000")
        self.second = settings.get("accent2", "#A8CE20")
        dark = luminance(self.primary) < 0.45
        # a dark brand colour needs a white stroke to read on dark footage; a light one a black stroke
        self.pri_outline = "#FFFFFF" if dark else "#000000"
        self.on_primary = "#FFFFFF" if dark else "#000000"
        self.on_second = "#FFFFFF" if luminance(self.second) < 0.45 else "#000000"
        self.events = []
        self.boxes = []  # (t0, t1, x0, y0, x1, y1, kind) for QC overlap checks

    # ---------- primitives ----------
    def ev(self, t0, t1, text, layer=1, style="Sub"):
        if t1 - t0 < 0.02:
            return
        self.events.append(f"Dialogue: {layer},{ts(t0)},{ts(t1)},{style},,0,0,0,,{text}")

    def shape(self, t0, t1, x, y, path, fill="#000000", fill_a=0, border=None, bord=0, border_a=0, blur=0,
              layer=0, extra=""):
        tags = (f"\\an7\\pos({x:.0f},{y:.0f})\\p1\\shad0\\bord{bord}\\blur{blur}"
                f"\\1c{ass_color(fill)}\\1a&H{fill_a:02X}&")
        if border:
            tags += f"\\3c{ass_color(border)}\\3a&H{border_a:02X}&"
        self.ev(t0, t1, "{" + tags + extra + "}" + path + "{\\p0}", layer)

    def card(self, t0, t1, x, y, w, h, r=28, fill="#0E0B08", fill_a=0x30, glow=True, extra="", layer=2):
        """Dark card with thin gold border and soft glow."""
        if glow:
            self.shape(t0, t1, x, y, rrect(w, h, r), fill="#000000", fill_a=0xFF, border=self.primary, bord=7,
                       border_a=0x90, blur=14, layer=layer, extra=extra)
        self.shape(t0, t1, x, y, rrect(w, h, r), fill=fill, fill_a=fill_a, border=self.primary, bord=3, blur=0.6,
                   layer=layer + 1, extra=extra)
        self.boxes.append((t0, t1, x, y, x + w, y + h, "card"))

    def text(self, t0, t1, x, y, s, size=60, family="Kanit ExtraBold", color="#FFFFFF", an=5, bord=4, shad=2,
             layer=5, extra="", outline="#000000"):
        tags = (f"\\an{an}\\pos({x:.0f},{y:.0f})\\fn{family}\\fs{size}\\1c{ass_color(color)}"
                f"\\3c{ass_color(outline)}\\bord{bord}\\shad{shad}\\4c&H000000&\\4a&H80&")
        self.ev(t0, t1, "{" + tags + extra + "}" + esc(s), layer)

    def atext(self, t0, t1, x, y, s, size=60, bord=4, layer=6, extra="", glow=True):
        """Text in the brand colour, stroked for contrast, with a soft brand-colour glow behind it."""
        if glow:
            self.text(t0, t1, x, y, s, size=size, color=self.primary, outline=self.primary, bord=bord + 8, shad=0,
                      layer=layer - 1, extra=extra + "\\blur14\\1a&HFF&\\3a&H60&")
        self.text(t0, t1, x, y, s, size=size, color=self.primary, outline=self.pri_outline, bord=bord, shad=0,
                  layer=layer, extra=extra)

    def label(self, t0, t1, s, x=60, y=180):
        """Small pill tag such as 'ภาพประกอบ' / 'ภาพสร้างด้วย AI'."""
        size = 30
        w = text_width(s, "Kanit SemiBold", size) + 66
        fade = "\\fad(200,150)"
        self.shape(t0, t1, x, y, rrect(w, 50, 25), fill="#000000", fill_a=0x50, border=self.primary, bord=2,
                   layer=6, extra=fade)
        self.shape(t0, t1, x + 18, y + 18, circle(14), fill=self.second, layer=7, extra=fade)
        self.text(t0, t1, x + 11 + w / 2, y + 25, s, size=size, family="Kanit SemiBold", color="#FFFFFF", bord=0, shad=0,
                  layer=7, extra=fade)

    # ---------- subtitles ----------
    def subtitles(self, phrases, y, size, mode="keyword"):
        hl = ass_color(self.primary)
        white = "&HFFFFFF&"
        hl_on = "{\\1c" + hl + "\\3c" + ass_color(self.pri_outline) + "}"
        hl_off = "{\\1c" + white + "\\3c&H000000&}"
        max_w = SAFE["right"] - SAFE["left"] - 40
        fnt = self.st.get("subtitle_font") or "Kanit ExtraBold"
        fnt = fnt if fnt in FONT_FILES else "Kanit ExtraBold"
        for p in phrases:
            sz = fit_size(p["text"], fnt, size, max_w)
            t0, t1 = p["s"], p["e"]
            base = (f"\\an5\\pos(540,{y:.0f})\\fn{fnt}\\fs{sz}\\bord6\\shad3\\3c&H000000&"
                    f"\\4c&H000000&\\4a&H60&")
            pop = "\\fscx82\\fscy82\\t(0,110,\\fscx104\\fscy104)\\t(110,170,\\fscx100\\fscy100)"
            self.boxes.append((t0, t1, 540 - text_width(p["text"], fnt, sz) / 2, y - sz * 0.75,
                               540 + text_width(p["text"], fnt, sz) / 2, y + sz * 0.75, "sub"))
            if mode == "karaoke":
                timed = [i for i, w in enumerate(p["parts"]) if w["s"] is not None]
                for k, i in enumerate(timed):
                    a = p["parts"][i]["s"] if k else t0
                    b = p["parts"][timed[k + 1]]["s"] if k + 1 < len(timed) else t1
                    body = ""
                    for j, w in enumerate(p["parts"]):
                        body += (hl_on if (j == i or w["hl"]) else hl_off) + esc(w["w"])
                    self.ev(a, b, "{" + base + (pop + "\\fad(60,0)" if k == 0 else "") + "}" + body, layer=20)
                continue
            body, glow = "", ""
            for w in p["parts"]:
                if w["hl"]:
                    body += hl_on + esc(w["w"]) + hl_off
                    glow += "{\\1a&H00&\\3a&H40&}" + esc(w["w"]) + "{\\1a&HFF&\\3a&HFF&}"
                else:
                    body += esc(w["w"])
                    glow += esc(w["w"])
            if any(w["hl"] for w in p["parts"]):
                gtags = base.replace("\\bord6", "\\bord12").replace("\\shad3", "\\shad0")
                self.ev(t0, t1, "{" + gtags + f"\\blur10\\1c{hl}\\3c{hl}\\1a&HFF&\\3a&HFF&"
                        + pop + "\\fad(60,40)}" + glow, layer=19)
            self.ev(t0, t1, "{" + base + pop + "\\fad(60,40)}" + body, layer=20)

    # ---------- composite graphics ----------
    def divider(self, t0, t1, y=960):
        self.shape(t0, t1, 0, y - 3, rrect(W, 6, 3), fill=self.primary, fill_a=0x60, blur=8, layer=8)
        self.shape(t0, t1, 0, y - 2, rrect(W, 4, 2), fill=self.primary, layer=9)

    def frame(self, t0, t1, x, y, w, h):
        self.shape(t0, t1, x, y, rrect(w, h, 34), fill="#000000", fill_a=0xFF, border=self.primary, bord=6,
                   border_a=0xA0, blur=12, layer=8)
        self.shape(t0, t1, x, y, rrect(w, h, 34), fill="#000000", fill_a=0xFF, border=self.primary, bord=2.5,
                   layer=9)

    def title_card(self, t0, t1, s, y=330):
        size = fit_size(s, "Kanit ExtraBold", 92, 900)
        lines = [s] if text_width(s, "Kanit ExtraBold", size) <= 900 else wrap(s, "Kanit ExtraBold", 76, 900, 2)
        if len(lines) > 1:
            size = 76
        h = int(size * 1.35 * len(lines) + 60)
        x, w = 60, 960
        top = y - h / 2
        fade = "\\fad(180,200)"
        self.shape(t0, t1, x, top, rrect(w, h, 26), fill="#000000", fill_a=0x48, layer=10,
                   extra=fade + "\\clip(0,0,0,1920)\\t(0,260,\\clip(0,0,1080,1920))")
        for dy in (top, top + h - 6):
            self.shape(t0, t1, x + 40, dy, rrect(w - 80, 6, 3), fill=self.primary, layer=11,
                       extra=fade + "\\clip(540,0,540,1920)\\t(60,360,\\clip(0,0,1080,1920))")
            self.shape(t0, t1, x + 40, dy - 4, rrect(w - 80, 14, 7), fill=self.primary, fill_a=0x70, blur=10,
                       layer=10, extra=fade)
        self.shape(t0, t1, x + w - 40 - 9, top - 6, circle(18), fill=self.second, layer=12,
                   extra=fade + "\\fscx0\\fscy0\\t(300,450,\\fscx120\\fscy120)\\t(450,520,\\fscx100\\fscy100)")
        for i, line in enumerate(lines):
            ly = top + 30 + size * 0.67 + i * size * 1.35
            self.text(t0, t1, 540, ly, line, size=size, color="#FFFFFF", bord=3, shad=0, layer=12,
                      extra=fade + f"\\move(500,{ly:.0f},540,{ly:.0f},0,280)")
        self.boxes.append((t0, t1, x, top, x + w, top + h, "title"))

    def stat(self, t0, t1, value, unit, caption, note, panel=(0, 0, W, 960), t_spoken=None):
        px, py, pw, ph = panel
        cw, ch = 820, 520
        cx, cy = px + (pw - cw) / 2, py + max(SAFE["top"] + 40, (ph - ch) / 2 + 40)
        pop = "\\fad(150,150)\\fscx90\\fscy90\\t(0,180,\\fscx100\\fscy100)"
        self.card(t0, t1, cx, cy, cw, ch, extra="\\fad(150,150)")
        raw = value.replace(",", "")
        is_year = len(raw) == 4 and raw.isdigit() and raw[:2] in ("15", "16", "17", "18", "19", "20", "25")
        size = fit_size(value + (" " + unit if unit else ""), "Kanit ExtraBold", 190, cw - 80)
        try:
            target = float(raw.rstrip("%"))
        except ValueError:
            target = None
        steps = 12
        card_t0, t0 = t0, max(t0, t_spoken if t_spoken is not None else t0)
        if t0 > card_t0 + 0.1:  # placeholder mark until the number is spoken
            self.text(card_t0, t0, 540, cy + ch * 0.42, "?", size=size, color="#4A4440", bord=0, shad=0, layer=6,
                      extra="\\fad(150,0)")
        if target is not None and not is_year and target >= 2:
            dur = min(0.7, (t1 - t0) * 0.4)
            for k in range(steps):
                a = t0 + dur * k / steps
                b = t0 + dur * (k + 1) / steps
                v = target * ((k + 1) / steps) ** 0.6
                vs = f"{int(round(v)):,}" if "," in value else str(int(round(v)))
                if "%" in value:
                    vs += "%"
                self.atext(a, b, 540, cy + ch * 0.42, vs + (" " + unit if unit else ""), size=size, bord=5,
                           glow=False)
            t_num = t0 + dur
        else:
            t_num = t0
        self.atext(t_num, t1, 540, cy + ch * 0.42, value + (" " + unit if unit else ""), size=size, bord=5,
                   extra="\\fad(0,150)" + ("" if t_num > t0 else pop))
        if caption:
            cs = fit_size(caption, "Kanit SemiBold", 54, cw - 80)
            self.text(card_t0, t1, 540, cy + ch * 0.75, caption, size=cs, family="Kanit SemiBold", bord=0, shad=0,
                      layer=6, extra="\\fad(250,150)")
        if note:
            self.text(card_t0, t1, 540, cy + ch - 34, note, size=26, family="Kanit", color="#BBBBBB", bord=0, shad=0,
                      layer=6, extra="\\fad(250,150)")

    def timeline(self, t0, t1, year, caption, panel=(0, 0, W, 960)):
        px, py, pw, ph = panel
        ly = py + ph * 0.58
        grow = "\\clip(0,0,0,1920)\\t(0,600,\\clip(0,0,1080,1920))"
        self.shape(t0, t1, 90, ly - 2, rrect(900, 5, 2), fill=self.primary, layer=4, extra="\\fad(100,150)" + grow)
        self.shape(t0, t1, 90, ly - 6, rrect(900, 14, 7), fill=self.primary, fill_a=0x80, blur=10, layer=3,
                   extra="\\fad(100,150)" + grow)
        for k in range(7):
            x = 120 + k * 140
            self.shape(t0 + 0.05 * k, t1, x - 2, ly - 16, rrect(4, 32, 2), fill="#FFFFFF", fill_a=0x80, layer=4,
                       extra="\\fad(150,150)")
        d = 56
        pop = "\\fscx10\\fscy10\\t(350,550,\\fscx115\\fscy115)\\t(550,650,\\fscx100\\fscy100)\\fad(0,150)"
        self.shape(t0, t1, 540 - d / 2, ly - d / 2, circle(d), fill=self.second, border=self.second, bord=10,
                   border_a=0x90, blur=6, layer=5, extra="\\an7" + pop)
        self.atext(t0 + 0.3, t1, 540, ly - 150, year, size=150, bord=5,
                   extra="\\fad(200,150)\\move(540,%d,540,%d,0,300)" % (ly - 110, ly - 150))
        if caption:
            cs = fit_size(caption, "Kanit SemiBold", 56, 880)
            self.text(t0 + 0.5, t1, 540, ly + 90, caption, size=cs, family="Kanit SemiBold", bord=3, shad=0, layer=6,
                      extra="\\fad(250,150)")
        self.boxes.append((t0, t1, 90, ly - 240, 990, ly + 130, "timeline"))

    def steps(self, t0, t1, items, times, panel=(0, 0, W, 960)):
        px, py, pw, ph = panel
        n = len(items)
        row_h = min(190, (ph - SAFE["top"] - 80) / n)
        top = py + max(SAFE["top"] + 20, (ph - row_h * n) / 2 + 30)
        for k, (item, ta) in enumerate(zip(items, times)):
            ta = max(t0, min(ta, t1 - 0.3))
            nxt = times[k + 1] if k + 1 < n else t1
            y = top + k * row_h
            slide = "\\fad(180,150)\\move(%d,%d,%d,%d,0,220)"
            self.card(ta, t1, 90, y, 900, row_h - 30, r=22, glow=False,
                      extra=slide % (130, y, 90, y), layer=2)
            # active step glows
            self.shape(ta, max(ta + 0.1, nxt), 90, y, rrect(900, row_h - 30, 22), fill="#000000", fill_a=0xFF,
                       border=self.primary, bord=7, border_a=0x80, blur=12, layer=1, extra="\\fad(150,150)")
            d = row_h - 70
            cy = y + (row_h - 30) / 2
            self.shape(ta, t1, 120, cy - d / 2, circle(d), fill=self.primary, layer=4,
                       extra=slide % (160, cy - d / 2, 120, cy - d / 2))
            self.text(ta, t1, 120 + d / 2, cy, str(k + 1), size=int(d * 0.8), color=self.on_primary, bord=0, shad=0,
                      layer=5, extra=slide % (160 + d / 2, cy, 120 + d / 2, cy))
            label = item
            size = fit_size(label, "Kanit SemiBold", 50, 900 - d - 90)
            if text_width(label, "Kanit SemiBold", size) > 900 - d - 90:
                label = wrap(label, "Kanit SemiBold", size, 900 - d - 90, 1)[0]
            self.text(ta, t1, 150 + d, cy, label, size=size, family="Kanit SemiBold", an=4, bord=0, shad=0, layer=5,
                      extra=slide % (190 + d, cy, 150 + d, cy))
        self.boxes.append((t0, t1, 90, top, 990, top + n * row_h, "steps"))

    def keyword(self, t0, t1, word, panel=(0, 0, W, 960)):
        px, py, pw, ph = panel
        size = fit_size(word, "Kanit ExtraBold", 150, 820)
        cw = min(940, text_width(word, "Kanit ExtraBold", size) + 140)
        ch = size * 1.6
        cx, cy = 540 - cw / 2, py + ph / 2 - ch / 2 + 40
        self.card(t0, t1, cx, cy, cw, ch, extra="\\fad(150,150)")
        self.atext(t0, t1, 540, cy + ch / 2, word, size=size, bord=5,
                   extra="\\fad(150,150)\\fscx70\\fscy70\\t(0,200,\\fscx100\\fscy100)")

    def compare(self, t0, t1, left, right, panel=(0, 0, W, 960)):
        px, py, pw, ph = panel
        cw, chh = 450, 420
        y = py + max(SAFE["top"] + 30, (ph - chh) / 2 + 40)
        for i, (s, x) in enumerate(((left, 60), (right, 570))):
            ta = t0 + 0.25 * i
            self.card(ta, t1, x, y, cw, chh, extra="\\fad(150,150)")
            lines = wrap(s, "Kanit SemiBold", 52, cw - 60, 3)
            for k, line in enumerate(lines):
                self.text(ta, t1, x + cw / 2, y + chh / 2 + (k - (len(lines) - 1) / 2) * 70, line, size=52,
                          family="Kanit SemiBold", bord=0, shad=0, layer=6, extra="\\fad(150,150)")
        d = 110
        self.shape(t0 + 0.4, t1, 540 - d / 2, y + chh / 2 - d / 2, circle(d), fill=self.second, border=self.primary,
                   bord=4, layer=7, extra="\\fad(150,150)")
        self.text(t0 + 0.4, t1, 540, y + chh / 2, "VS", size=56, color=self.on_second, bord=0, shad=0, layer=8,
                  extra="\\fad(150,150)")

    def placeholder(self, t0, t1, description, prompt, panel=(0, 0, W, 960)):
        """Clearly-marked slot for a visual that still has to be created/sourced."""
        px, py, pw, ph = panel
        x, y, w, h = 70, py + SAFE["top"] + 100, 940, ph - SAFE["top"] - 150
        # dashed border
        seg, gap = 34, 18
        k = 0
        while k * (seg + gap) < w - 40:
            xx = x + 20 + k * (seg + gap)
            for yy in (y, y + h - 4):
                self.shape(t0, t1, xx, yy, rrect(min(seg, x + w - 20 - xx), 4, 2), fill=self.primary, layer=4,
                           extra="\\fad(150,150)")
            k += 1
        k = 0
        while k * (seg + gap) < h - 40:
            yy = y + 20 + k * (seg + gap)
            for xx in (x, x + w - 4):
                self.shape(t0, t1, xx, yy, rrect(4, min(seg, y + h - 20 - yy), 2), fill=self.primary, layer=4,
                           extra="\\fad(150,150)")
            k += 1
        self.atext(t0, t1, 540, y + 80, "PLACEHOLDER · ต้องเพิ่มภาพ", size=46, bord=3, glow=False,
                   extra="\\fad(150,150)")
        lines = wrap(description, "Kanit SemiBold", 46, w - 120, 3)
        for i, line in enumerate(lines):
            self.text(t0, t1, 540, y + 170 + i * 64, line, size=46, family="Kanit SemiBold", bord=0, shad=0, layer=6,
                      extra="\\fad(150,150)")
        if prompt:
            plines = wrap("AI prompt: " + prompt, "Kanit", 28, w - 140, 3)
            for i, line in enumerate(plines):
                self.text(t0, t1, 540, y + h - 60 - (len(plines) - 1 - i) * 40, line, size=28, family="Kanit",
                          color="#BBBBBB", bord=0, shad=0, layer=6, extra="\\fad(150,150)")

    def document(self, fonts_dir_note=""):
        st = self.st
        head = f"""[Script Info]
; generated by AutoEdit {fonts_dir_note}
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Kanit ExtraBold,{st.get('subtitle_size', 78)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,6,3,5,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        return head + "\n".join(self.events) + "\n"
