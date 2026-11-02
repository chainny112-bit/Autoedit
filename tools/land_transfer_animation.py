"""Animated explainer (no narration, no subtitles): the house-transfer day at the Land Office, step by step.

Everything is drawn as vectors with libass (ASS drawing commands) and rendered by FFmpeg, with generated
music and pop/whoosh effects. 9:16, 1080x1920.

Usage: python3 tools/land_transfer_animation.py OUT.mp4 [--photo IMG ...]
  --photo  real customer photos for the "ตัวอย่างลูกค้าของเรา" scene (up to 9). Without them the scene shows an
           illustration clearly labelled "ภาพประกอบ".
"""
import argparse
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import FONTS_DIR, ROOT, media   # noqa: E402
from engine.graphics import Script, ass_color, circle, esc, fit_size, rrect, ts   # noqa: E402
from engine.render import synth_sfx   # noqa: E402

W, H, FPS = 1080, 1920, 30
BG = "#FFF6EE"
RED, RED_D, LIME = "#BC0000", "#8E0000", "#A8CE20"
INK, GREY, LGREY, WHITE = "#2B1D1D", "#8C8484", "#E9E1DA", "#FFFFFF"
SKIN, SKIN2, HAIR = "#F2C9A0", "#E0A97A", "#3A2A22"
BLUE, TEAL, GOLD = "#3D6FB6", "#2F9E8F", "#F2B21B"

sc = Script({"accent": RED, "accent2": LIME})
SFX = []          # (time, kind)
SPRITES = []      # animated character instances, composited under the ASS layer by FFmpeg
SPRITE_DIR = ROOT / "assets/characters/sprites"
SPRITE_W, SPRITE_H = 440, 590   # sprite frame (viewBox crop of assets/characters/animated_character.svg)


def char(t0, t1, cx, top, h, variant, anim="rise", delay=0.0, flip=False):
    """Place the animated SVG character (pre-rendered sprite) centred at cx with its frame top at `top`."""
    SPRITES.append({"t0": t0 + delay, "t1": t1, "cx": cx, "top": top, "h": h, "variant": variant, "anim": anim,
                    "flip": flip})


def sprite_graph(start, idx0):
    """FFmpeg inputs + overlay chain for every SPRITES entry. Returns (inputs, graph, last_label)."""
    inputs, g, cur, idx = [], "", start, idx0
    for k, sp in enumerate(SPRITES):
        path = SPRITE_DIR / f"{sp['variant']}.webm"
        if not path.exists():
            raise SystemExit(f"ไม่พบ sprite {path} — สร้างด้วย: node tools/render_character_sprites.js")
        w = round(sp["h"] * SPRITE_W / SPRITE_H / 2) * 2
        h = round(sp["h"] / 2) * 2
        x, y, t0 = sp["cx"] - w / 2, sp["top"], sp["t0"]
        e = f"min(1,max(0,(t-{t0:.3f})/0.38))"
        if sp["anim"] == "left":
            xe, ye = f"{x:.0f}+({-w - 40:.0f}-{x:.0f})*pow(1-{e},3)", f"{y:.0f}"
        elif sp["anim"] == "right":
            xe, ye = f"{x:.0f}+({W + 40:.0f}-{x:.0f})*pow(1-{e},3)", f"{y:.0f}"
        else:
            xe, ye = f"{x:.0f}", f"{y:.0f}+70*pow(1-{e},3)"
        phase = (k * 0.73) % 6   # characters don't blink in unison
        # libvpx decoder is required to keep the alpha channel of VP9 sprites
        inputs += ["-stream_loop", "-1", "-ss", f"{phase:.2f}", "-c:v", "libvpx-vp9", "-i", str(path)]
        g += (f";[{idx}:v]scale={w}:{h},format=rgba{',hflip' if sp['flip'] else ''},"
              f"fade=t=in:st={t0:.3f}:d=0.2:alpha=1[sp{k}];"
              f"[{cur}][sp{k}]overlay=x='{xe}':y='{ye}':enable='between(t,{t0:.3f},{sp['t1']:.3f})'[sc{k}]")
        cur = f"sc{k}"
        idx += 1
    return inputs, g, cur, idx


# ------------------------------------------------------------------ drawing primitives
def poly(pts):
    return "m %d %d " % pts[0] + " ".join("l %d %d" % p for p in pts[1:])


def ellipse(w, h):
    rx, ry = w / 2, h / 2
    kx, ky = rx * 0.552, ry * 0.552
    return (f"m {rx:.0f} 0 b {rx + kx:.0f} 0 {w:.0f} {ry - ky:.0f} {w:.0f} {ry:.0f} "
            f"b {w:.0f} {ry + ky:.0f} {rx + kx:.0f} {h:.0f} {rx:.0f} {h:.0f} "
            f"b {rx - kx:.0f} {h:.0f} 0 {ry + ky:.0f} 0 {ry:.0f} b 0 {ry - ky:.0f} {rx - kx:.0f} 0 {rx:.0f} 0")


def anim_tags(x, y, anim, delay):
    """Position + entrance animation. All parts of one object share these so they stay aligned."""
    d0 = int(delay * 1000)
    if anim == "rise":
        return f"\\move({x:.0f},{y + 60:.0f},{x:.0f},{y:.0f},{d0},{d0 + 320})\\fad({d0 + 220},160)"
    if anim == "drop":
        return f"\\move({x:.0f},{y - 700:.0f},{x:.0f},{y:.0f},{d0},{d0 + 420})\\fad({d0 + 80},160)"
    if anim == "left":
        return f"\\move({x - 700:.0f},{y:.0f},{x:.0f},{y:.0f},{d0},{d0 + 380})\\fad({d0 + 120},160)"
    if anim == "right":
        return f"\\move({x + 700:.0f},{y:.0f},{x:.0f},{y:.0f},{d0},{d0 + 380})\\fad({d0 + 120},160)"
    return f"\\pos({x:.0f},{y:.0f})\\fad({d0 + 200},160)"


def shape(t0, t1, x, y, path, fill, layer=5, anim="fade", delay=0.0, border=None, bord=0, alpha=0, blur=0, extra=""):
    t0, delay = t0 + delay, 0.0
    tags = (f"\\an7{anim_tags(x, y, anim, delay)}\\p1\\shad0\\bord{bord}\\blur{blur}"
            f"\\1c{ass_color(fill)}\\1a&H{alpha:02X}&")
    if border:
        tags += f"\\3c{ass_color(border)}"
    sc.ev(t0, t1, "{" + tags + extra + "}" + path + "{\\p0}", layer)


def group(t0, t1, ox, oy, parts, anim="rise", delay=0.0, layer=5):
    """parts: (dx, dy, path, fill[, kwargs]) drawn relative to (ox, oy) with one shared animation."""
    for i, p in enumerate(parts):
        dx, dy, path, fill = p[:4]
        kw = p[4] if len(p) > 4 else {}
        shape(t0, t1, ox + dx, oy + dy, path, fill, layer=layer + kw.pop("z", 0), anim=anim, delay=delay, **kw)


def text(t0, t1, x, y, s, size=64, color=INK, family="Kanit ExtraBold", pop=True, delay=0.0, layer=30, bord=0,
         outline=WHITE, an=5):
    t0, delay = t0 + delay, 0.0
    d0 = 0
    anim = (f"\\fscx20\\fscy20\\t({d0},{d0 + 170},\\fscx112\\fscy112)\\t({d0 + 170},{d0 + 260},\\fscx100\\fscy100)"
            f"\\fad({d0 + 60},150)") if pop else f"\\fad({d0 + 200},150)"
    sc.ev(t0, t1, "{" + f"\\an{an}\\pos({x:.0f},{y:.0f})\\fn{family}\\fs{size}\\1c{ass_color(color)}"
          f"\\3c{ass_color(outline)}\\bord{bord}\\shad0" + anim + "}" + esc(s), layer)


def bubble(t0, t1, x, y, s, size=58, fill=WHITE, color=INK, delay=0.0, border=RED, tail=None, layer=28, sfx=True):
    """Pop-up callout card (the 'text that bounces in')."""
    t0, delay = t0 + delay, 0.0
    size = fit_size(s, "Kanit ExtraBold", size, 900)
    from engine.graphics import text_width
    w = text_width(s, "Kanit ExtraBold", size) + 80
    h = size * 1.55
    d0 = int(delay * 1000)
    pop = (f"\\fscx15\\fscy15\\t({d0},{d0 + 180},\\fscx110\\fscy110)\\t({d0 + 180},{d0 + 270},\\fscx100\\fscy100)"
           f"\\fad({d0 + 50},150)")
    sc.ev(t0, t1, "{" + f"\\an5\\pos({x + 10:.0f},{y + 14:.0f})\\p1\\bord0\\shad0\\blur6\\1c&H000000&\\1a&HB0&"
          + pop + "}" + rrect(w, h, h / 2) + "{\\p0}", layer)
    sc.ev(t0, t1, "{" + f"\\an5\\pos({x:.0f},{y:.0f})\\p1\\bord5\\shad0\\1c{ass_color(fill)}\\3c{ass_color(border)}"
          + pop + "}" + rrect(w, h, h / 2) + "{\\p0}", layer + 1)
    if tail:   # little triangle pointing at what the text describes
        tx, ty = tail
        sc.ev(t0, t1, "{" + f"\\an7\\pos({tx - 22:.0f},{ty:.0f})\\p1\\bord0\\shad0\\1c{ass_color(border)}"
              f"\\fad({d0 + 120},150)" + "}" + poly([(0, 0), (44, 0), (22, 34)]) + "{\\p0}", layer)
    text(t0, t1, x, y, s, size=size, color=color, delay=delay, layer=layer + 2)
    if sfx:
        SFX.append((t0 + delay + 0.02, "pop"))


def step_badge(t0, t1, n, title, total=7):
    """Top bar: STEP n + progress dots, then the step title."""
    shape(t0, t1, 60, 150, rrect(250, 92, 46), RED, layer=40, anim="left")
    text(t0, t1, 185, 196, f"STEP {n}", size=52, color=WHITE, pop=False, layer=41)
    for k in range(total):
        c = RED if k < n else LGREY
        shape(t0, t1, 360 + k * 92, 184, circle(26) if k + 1 != n else rrect(60, 26, 13), c if k + 1 != n else LIME,
              layer=40, anim="fade", delay=0.1 + 0.04 * k)
    text(t0, t1, 540, 330, title, size=fit_size(title, "Kanit ExtraBold", 92, 960), color=INK, delay=0.15, layer=41)
    SFX.append((t0 + 0.15, "pop"))


def wipe(t):
    """Brand wipe between scenes: red panel + lime stripe sweep across the frame, centred on the cut."""
    sc.ev(t - 0.32, t + 0.32, "{" + f"\\an7\\move(-1300,0,1300,0)\\p1\\bord0\\shad0\\1c{ass_color(RED)}" + "}"
          + poly([(0, 0), (1200, 0), (1080, 1920), (-120, 1920)]) + "{\\p0}", 90)
    sc.ev(t - 0.32, t + 0.32, "{" + f"\\an7\\move(-1420,0,1180,0)\\p1\\bord0\\shad0\\1c{ass_color(LIME)}" + "}"
          + poly([(0, 0), (90, 0), (-30, 1920), (-120, 1920)]) + "{\\p0}", 91)
    SFX.append((t - 0.25, "whoosh"))


# ------------------------------------------------------------------ illustrations (local coords)
def person(shirt, pants="#3B3F4A", hair=HAIR, skin=SKIN, sit=False, arm_up=False, s=1.0):
    k = lambda v: v * s   # noqa: E731
    parts = [
        (k(18), k(0), ellipse(k(64), k(70)), skin),
        (k(14), k(-6), rrect(k(72), k(34), k(17)), hair),
        (k(0), k(72), rrect(k(100), k(120), k(36)), shirt),
    ]
    if sit:
        parts += [(k(6), k(170), rrect(k(130), k(36), k(16)), pants), (k(104), k(170), rrect(k(32), k(90), k(14)), pants)]
    else:
        parts += [(k(14), k(176), rrect(k(30), k(110), k(14)), pants), (k(56), k(176), rrect(k(30), k(110), k(14)), pants)]
    if arm_up:
        parts += [(k(84), k(20), rrect(k(26), k(90), k(13)), shirt), (k(84), k(4), circle(k(30)), skin)]
    return parts


def chair():
    return [(0, 0, rrect(150, 26, 10), GREY), (10, 26, rrect(18, 80, 6), GREY), (122, 26, rrect(18, 80, 6), GREY),
            (118, -120, rrect(26, 130, 10), GREY)]


def house(scale=1.0, wall=WHITE, roof=RED):
    k = lambda v: v * scale   # noqa: E731
    return [(0, k(130), rrect(k(300), k(200), k(14)), wall, {"border": INK, "bord": 6}),
            (k(-30), 0, poly([(0, k(140)), (k(180), 0), (k(360), k(140))]), roof, {"border": INK, "bord": 6, "z": 1}),
            (k(115), k(220), rrect(k(70), k(110), k(10)), "#C48A4E", {"border": INK, "bord": 5, "z": 1}),
            (k(30), k(180), rrect(k(60), k(60), k(8)), "#A9D8F5", {"border": INK, "bord": 5, "z": 1}),
            (k(210), k(180), rrect(k(60), k(60), k(8)), "#A9D8F5", {"border": INK, "bord": 5, "z": 1})]


def key(color=GOLD, s=1.0):
    k = lambda v: v * s   # noqa: E731
    return [(0, 0, circle(k(90)), color, {"border": INK, "bord": 5}), (k(28), k(28), circle(k(34)), BG, {"z": 1}),
            (k(84), k(36), rrect(k(170), k(20), k(8)), color, {"border": INK, "bord": 5}),
            (k(200), k(54), rrect(k(20), k(36), k(4)), color, {"border": INK, "bord": 4}),
            (k(160), k(54), rrect(k(20), k(28), k(4)), color, {"border": INK, "bord": 4})]


def document(w=360, h=460, lines=6, title_color=RED):
    parts = [(0, 0, rrect(w, h, 18), WHITE, {"border": INK, "bord": 6}),
             (40, 40, rrect(w * 0.55, 26, 13), title_color, {"z": 1})]
    for i in range(lines):
        parts.append((40, 100 + i * 46, rrect((w - 80) * (0.95 if i % 3 else 0.7), 16, 8), LGREY, {"z": 1}))
    return parts


def deed():
    """Title deed (โฉนด) — generic illustration: emblem + lines, no real document details."""
    parts = [(0, 0, rrect(420, 540, 16), "#FFF9E6", {"border": INK, "bord": 6}),
             (20, 20, rrect(380, 500, 10), "#FFF9E6", {"border": GOLD, "bord": 4, "z": 1}),
             (170, 50, circle(80), GOLD, {"border": INK, "bord": 4, "z": 2}),
             (190, 70, circle(40), "#FFF9E6", {"z": 3})]
    for i in range(6):
        parts.append((60, 170 + i * 52, rrect(300 if i % 2 else 240, 14, 7), "#D9CBB0", {"z": 2}))
    return parts


# ------------------------------------------------------------------ scenes
def scene_intro(a, b):
    shape(a, b, 0, 1380, rrect(1080, 540, 0), "#FBE3D6", layer=2)
    group(a, b, 390, 760, house(1.0), anim="drop", delay=0.1, layer=10)
    SFX.append((a + 0.5, "hit"))
    group(a, b, 640, 1060, key(s=0.9), anim="right", delay=0.6, layer=14)
    text(a, b, 540, 380, "เราจะพามาดู", size=70, color=GREY, delay=0.2)
    bubble(a, b, 540, 520, "ขั้นตอนการโอนบ้าน", size=104, fill=RED, color=WHITE, border=RED_D, delay=0.45)
    text(a, b, 540, 1520, "ตั้งแต่ไปถึงสำนักงานที่ดิน", size=58, color=INK, delay=1.1)
    text(a, b, 540, 1600, "จนได้รับโฉนด", size=58, color=RED, delay=1.3)


def scene_location(a, b):
    # simple map with roads, pin drops on the Land Office
    shape(a, b, 60, 560, rrect(960, 820, 40), "#E8F1E4", layer=2, border=INK, bord=6)
    for x0, y0, w0, h0 in ((60, 820, 960, 60), (420, 560, 60, 820), (760, 560, 50, 820), (60, 1180, 960, 50)):
        shape(a, b, x0, y0, rrect(w0, h0, 0), WHITE, layer=3)
    shape(a, b, 120, 620, rrect(240, 160, 20), "#CFE5C2", layer=3)
    shape(a, b, 540, 920, rrect(180, 220, 20), "#CFE5C2", layer=3)
    # office building
    bld = [(0, 60, rrect(300, 220, 10), WHITE, {"border": INK, "bord": 6}),
           (-20, 0, poly([(0, 70), (170, 0), (340, 70)]), RED, {"border": INK, "bord": 6, "z": 1})]
    for i in range(4):
        bld.append((30 + i * 70, 110, rrect(30, 170, 6), LGREY, {"z": 1}))
    group(a, b, 190, 930, bld, anim="rise", delay=0.15, layer=6)
    pin = [(0, 0, poly([(0, 60), (60, 160), (120, 60), (110, 25), (60, 0), (10, 25)]), RED, {"border": INK, "bord": 6}),
           (35, 30, circle(50), WHITE, {"z": 1})]
    group(a, b, 280, 800, pin, anim="drop", delay=0.5, layer=20)
    SFX.append((a + 0.9, "pop"))
    text(a, b, 540, 380, "วันนี้เราอยู่ที่", size=70, color=GREY, delay=0.1)
    bubble(a, b, 540, 1480, "กรมที่ดิน หาดใหญ่", size=90, fill=RED, color=WHITE, border=RED_D, delay=0.9)
    bubble(a, b, 540, 1640, "จ.สงขลา", size=72, delay=1.3, border=LIME)


def scene_queue(a, b):
    step_badge(a, b, 1, "หยิบบัตรคิว แล้วนั่งรอ")
    # ticket machine + ticket sliding out
    mach = [(0, 0, rrect(260, 420, 30), "#D6DCE5", {"border": INK, "bord": 6}),
            (40, 50, rrect(180, 120, 14), "#2B3A55", {"z": 1}),
            (90, 230, circle(80), RED, {"border": INK, "bord": 5, "z": 1}),
            (60, 360, rrect(140, 16, 8), INK, {"z": 1})]
    group(a, b, 120, 500, mach, anim="rise", delay=0.1)
    shape(a, b, 165, 880, rrect(170, 220, 14), WHITE, layer=9, border=INK, bord=5,
          extra=f"\\clip(0,875,1080,1920)\\move(165,760,165,880,600,1000)")
    text(a, b, 250, 990, "A012", size=60, color=RED, delay=0.85, layer=12)
    bubble(a, b, 640, 690, "หยิบบัตรคิวก่อน", size=64, delay=0.7, tail=(470, 720))
    # people seated behind a waiting bench (the bench is drawn over their legs)
    for i, (cx, v) in enumerate(((600, "blue_idle"), (860, "teal_idle"))):
        char(a, b, cx, 1032, 350, v, delay=1.7 + 0.15 * i)
    bench = [(0, 0, rrect(620, 34, 14), "#9C6F45", {"border": INK, "bord": 5, "z": 1}),
             (10, 34, rrect(600, 110, 10), "#B8875A", {"border": INK, "bord": 5}),
             (40, 144, rrect(26, 70, 8), GREY), (554, 144, rrect(26, 70, 8), GREY)]
    group(a, b, 420, 1290, bench, anim="rise", delay=1.6, layer=8)
    bubble(a, b, 540, 1600, "นั่งรอเรียกคิว", size=70, delay=2.3, border=LIME)


def scene_call(a, b):
    step_badge(a, b, 2, "เจ้าหน้าที่เรียกคิว")
    board = [(0, 0, rrect(520, 240, 24), "#1F2633", {"border": INK, "bord": 6}),
             (30, 30, rrect(460, 180, 14), "#0E141C", {"z": 1})]
    group(a, b, 280, 470, board, anim="rise", delay=0.1)
    sc.ev(a + 0.6, b, "{" + "\\an5\\pos(540,590)\\fnKanit ExtraBold\\fs120\\1c" + ass_color(LIME) +
          "\\bord0\\shad0\\fad(100,100)\\t(0,150,\\alpha&HFF&)\\t(150,300,\\alpha&H00&)\\t(300,450,\\alpha&HFF&)"
          "\\t(450,600,\\alpha&H00&)" + "}A012", 12)
    SFX.append((a + 0.6, "pop"))
    SFX.append((a + 0.9, "pop"))
    # officer at desk
    char(a, b, 760, 700, 480, "navy_wave", delay=0.4)
    group(a, b, 330, 1130, [(0, 0, rrect(620, 60, 14), "#B8875A", {"border": INK, "bord": 6}),
                            (30, 60, rrect(560, 300, 10), "#9C6F45", {"border": INK, "bord": 6})],
          anim="rise", delay=0.5, layer=9)
    group(a, b, 400, 1050, [(0, 0, rrect(170, 110, 10), "#2B3A55", {"border": INK, "bord": 5}),
                            (70, 110, rrect(30, 30, 4), INK)], anim="rise", delay=0.6, layer=10)
    bubble(a, b, 540, 1620, "ถึงคิวแล้ว ไปที่ช่องบริการ", size=62, delay=1.1)


def scene_sign(a, b):
    step_badge(a, b, 3, "ผู้ซื้อ–ผู้ขาย เซ็นเอกสาร")
    char(a, b, 175, 690, 450, "blue_idle", anim="left", delay=0.1)
    char(a, b, 905, 690, 450, "red_idle", anim="right", delay=0.15, flip=True)
    text(a, b, 170, 1160, "ผู้ซื้อ", size=50, color=BLUE, delay=0.5)
    text(a, b, 910, 1160, "ผู้ขาย", size=50, color=RED, delay=0.55)
    group(a, b, 360, 560, document(), anim="rise", delay=0.3, layer=8)
    # signature drawn live
    sig = poly([(0, 40), (20, 0), (40, 50), (60, 10), (80, 45), (110, 5), (130, 50), (160, 20), (200, 40)])
    sc.ev(a + 1.0, b, "{" + "\\an7\\pos(420,900)\\p1\\bord6\\shad0\\1a&HFF&\\3c" + ass_color(BLUE)
          + "\\clip(420,850,420,1000)\\t(0,900,\\clip(420,850,640,1000))\\fad(0,150)" + "}" + sig + "{\\p0}", 12)
    pen = [(0, 0, poly([(0, 0), (24, 0), (24, 150), (12, 180), (0, 150)]), "#2B3A55", {"border": INK, "bord": 4})]
    sc.ev(a + 1.0, b, "{" + "\\an7\\move(420,760,620,760,0,900)\\p1\\bord4\\shad0\\1c" + ass_color("#2B3A55")
          + "\\3c" + ass_color(INK) + "\\fad(150,150)\\frz-25" + "}" + pen[0][2] + "{\\p0}", 13)
    bubble(a, b, 540, 1340, "เซ็นเอกสารให้ครบ", size=70, delay=1.9)
    sc.ev(a + 2.0, b, "{" + "\\an5\\pos(820,620)\\p1\\bord0\\shad0\\1c" + ass_color(LIME)
          + "\\fscx10\\fscy10\\t(0,200,\\fscx100\\fscy100)\\fad(0,150)" + "}" + circle(110) + "{\\p0}", 14)
    sc.ev(a + 2.1, b, "{" + "\\an7\\pos(782,600)\\p1\\bord8\\shad0\\1a&HFF&\\3c&HFFFFFF&"
          "\\clip(782,0,782,1920)\\t(0,250,\\clip(782,0,900,1920))" + "}" + poly([(0, 22), (22, 44), (64, 0)]) + "{\\p0}", 15)


def scene_pay(a, b):
    step_badge(a, b, 4, "ชำระเงินค่าโอนที่ช่อง")
    # counter frame around a see-through glass window, the cashier stands behind it
    counter = [(0, 0, rrect(760, 60, 20), "#D6DCE5", {"border": INK, "bord": 6}),
               (0, 0, rrect(60, 420, 20), "#D6DCE5", {"border": INK, "bord": 6}),
               (700, 0, rrect(60, 420, 20), "#D6DCE5", {"border": INK, "bord": 6}),
               (60, 60, rrect(640, 300, 18), "#BFE3F2", {"border": INK, "bord": 5, "z": 1, "alpha": 0xB0}),
               (0, 360, rrect(760, 60, 10), "#D6DCE5", {"border": INK, "bord": 6}),
               (0, 400, rrect(760, 50, 10), "#9C6F45", {"border": INK, "bord": 5, "z": 2}),
               (0, 450, rrect(760, 90, 10), "#D6DCE5", {"border": INK, "bord": 6})]
    group(a, b, 160, 560, counter, anim="rise", delay=0.1)
    char(a, b, 540, 590, 430, "teal_idle", delay=0.3)
    shape(a, b, 380, 490, rrect(320, 90, 20), RED, layer=11, anim="fade", delay=0.2)
    text(a, b, 540, 535, "ช่องชำระเงิน", size=52, color=WHITE, pop=False, layer=13)
    # banknote slides onto the counter, receipt pops
    note = [(0, 0, rrect(260, 130, 12), "#7FBF6A", {"border": INK, "bord": 5}),
            (95, 30, circle(70), "#5E9E4C", {"z": 1})]
    group(a, b, 200, 1090, note, anim="left", delay=0.8, layer=14)
    rec = [(0, 0, rrect(220, 280, 12), WHITE, {"border": INK, "bord": 5})]
    for i in range(4):
        rec.append((30, 40 + i * 40, rrect(160 if i % 2 else 120, 14, 7), LGREY, {"z": 1}))
    group(a, b, 660, 1000, rec, anim="rise", delay=1.6, layer=14)
    sc.ev(a + 1.9, b, "{" + "\\an5\\pos(770,1230)\\p1\\bord0\\shad0\\1c" + ass_color(LIME)
          + "\\fscx10\\fscy10\\t(0,200,\\fscx100\\fscy100)\\fad(0,150)" + "}" + circle(90) + "{\\p0}", 16)
    sc.ev(a + 2.0, b, "{" + "\\an7\\pos(740,1212)\\p1\\bord8\\shad0\\1a&HFF&\\3c&HFFFFFF&"
          "\\clip(740,0,740,1920)\\t(0,250,\\clip(740,0,840,1920))" + "}" + poly([(0, 18), (18, 36), (52, 0)]) + "{\\p0}", 17)
    bubble(a, b, 540, 1500, "ชำระค่าโอนเรียบร้อย", size=70, delay=1.9, border=LIME)


def scene_check_back(a, b):
    step_badge(a, b, 5, "ยืนรอเรียก ตรวจสอบหลังโฉนด")
    for i, (cx, v) in enumerate(((170, "blue_idle"), (330, "red_idle"), (490, "lime_idle"))):
        char(a, b, cx, 880, 360, v, delay=0.1 + 0.08 * i)
    group(a, b, 580, 560, deed(), anim="rise", delay=0.4, layer=8)
    text(a, b, 790, 1140, "หลังโฉนด", size=48, color=GREY, delay=0.6)
    # magnifier sweeping over the deed
    mag = (f"{circle(170)}")
    sc.ev(a + 0.9, b, "{" + "\\an7\\move(600,620,720,820,0,1400)\\p1\\bord10\\shad0\\1c&HFFFFFF&\\1a&HB0&\\3c"
          + ass_color(INK) + "\\fad(150,150)" + "}" + mag + "{\\p0}", 14)
    sc.ev(a + 0.9, b, "{" + "\\an7\\move(745,770,865,970,0,1400)\\p1\\bord0\\shad0\\1c" + ass_color(INK)
          + "\\frz-45\\fad(150,150)" + "}" + rrect(30, 130, 12) + "{\\p0}", 13)
    bubble(a, b, 540, 1440, "รอเจ้าหน้าที่เรียก", size=66, delay=1.4)
    bubble(a, b, 540, 1600, "เพื่อตรวจสอบหลังโฉนด", size=66, delay=1.9, border=LIME)


def scene_keys(a, b):
    text(a, b, 540, 330, "ระหว่างยืนรอ...", size=80, color=GREY, delay=0.1)
    char(a, b, 240, 690, 520, "red_idle", anim="left", delay=0.1)
    char(a, b, 840, 690, 520, "blue_idle", anim="right", delay=0.15, flip=True)
    text(a, b, 240, 1250, "ผู้ขาย", size=50, color=RED, delay=0.4)
    text(a, b, 840, 1250, "ผู้ซื้อ", size=50, color=BLUE, delay=0.45)
    # key travels from seller to buyer
    for i, p in enumerate(key(s=0.8)):
        dx, dy, path, fill = p[:4]
        kw = p[4] if len(p) > 4 else {}
        b_ = kw.get("bord", 0)
        sc.ev(a + 0.7, b, "{" + f"\\an7\\move({345 + dx:.0f},{985 + dy:.0f},{545 + dx:.0f},{970 + dy:.0f},300,1300)"
              f"\\p1\\bord{b_}\\shad0\\1c{ass_color(fill)}\\3c{ass_color(INK)}\\fad(200,150)" + "}" + path + "{\\p0}",
              20 + kw.get("z", 0))
    SFX.append((a + 1.0, "whoosh"))
    bubble(a, b, 540, 1400, "ส่งมอบกุญแจบ้าน", size=84, fill=RED, color=WHITE, border=RED_D, delay=1.8)
    group(a, b, 400, 1520, house(0.5), anim="rise", delay=2.2, layer=6)


def scene_receive(a, b):
    step_badge(a, b, 6, "รับโฉนด ตรวจชื่อให้ถูกต้อง")
    group(a, b, 330, 520, deed(), anim="rise", delay=0.1, layer=6)
    # name rows with check marks ticking one by one
    names = ["ชื่อผู้รับโอน", "เลขที่โฉนด", "รายละเอียดที่ดิน"]
    for i, n in enumerate(names):
        y = 1150 + i * 130
        d = 0.8 + 0.5 * i
        shape(a, b, 120, y, rrect(840, 104, 30), WHITE, layer=10, border=INK, bord=4, anim="rise", delay=d)
        text(a, b, 200, y + 52, n, size=50, color=INK, an=4, delay=d, layer=12)
        sc.ev(a + d + 0.3, b, "{" + f"\\an5\\pos(890,{y + 52})\\p1\\bord0\\shad0\\1c" + ass_color(LIME)
              + "\\fscx10\\fscy10\\t(0,180,\\fscx100\\fscy100)\\fad(0,150)" + "}" + circle(76) + "{\\p0}", 13)
        sc.ev(a + d + 0.4, b, "{" + f"\\an7\\pos(866,{y + 38})\\p1\\bord7\\shad0\\1a&HFF&\\3c&HFFFFFF&"
              f"\\clip(866,0,866,1920)\\t(0,200,\\clip(866,0,960,1920))" + "}" + poly([(0, 14), (14, 28), (44, 0)])
              + "{\\p0}", 14)
        SFX.append((a + d + 0.3, "pop"))
    bubble(a, b, 540, 1620, "ถูกต้องครบ รับโฉนดได้เลย", size=62, delay=2.4, border=LIME, sfx=False)


def scene_photo(a, b):
    step_badge(a, b, 7, "ถ่ายรูปแสดงความยินดี")
    # middle person last so they stand in front; the outer two wave
    for cx, v, d in ((300, "red_wave", 0.1), (780, "teal_wave", 0.2), (540, "blue_idle", 0.3)):
        char(a, b, cx, 740, 470, v, delay=d, flip=(cx > 540))
    small_deed = [(0, 0, rrect(210, 150, 10), "#FFF9E6", {"border": INK, "bord": 5}), (80, 30, circle(50), GOLD, {"z": 1})]
    group(a, b, 435, 1150, small_deed, anim="rise", delay=0.5, layer=12)
    # camera flash
    sc.ev(a + 1.2, a + 1.45, "{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c&HFFFFFF&\\fad(30,200)}"
          + rrect(1080, 1920, 0) + "{\\p0}", 80)
    SFX.append((a + 1.2, "hit"))
    # photo frame corners
    for (x, y, rot) in ((150, 680, 0), (930, 680, 90), (930, 1360, 180), (150, 1360, 270)):
        sc.ev(a + 1.3, b, "{" + f"\\an7\\pos({x},{y})\\p1\\bord0\\shad0\\1c{ass_color(INK)}\\frz{-rot}\\fad(100,150)"
              + "}" + poly([(0, 0), (90, 0), (90, 14), (14, 14), (14, 90), (0, 90)]) + "{\\p0}", 20)
    rnd = random.Random(3)
    for k in range(40):   # confetti
        x, y = rnd.uniform(60, 1020), rnd.uniform(-200, 300)
        c = rnd.choice([RED, LIME, GOLD, BLUE])
        d = rnd.uniform(0, 0.4)
        sc.ev(a + 1.3 + d, b, "{" + f"\\an5\\move({x:.0f},{y:.0f},{x + rnd.uniform(-120, 120):.0f},{y + 1500:.0f},0,2600)"
              f"\\frz{rnd.uniform(0, 360):.0f}\\t(\\frz{rnd.uniform(400, 900):.0f})\\p1\\bord0\\shad0"
              f"\\1c{ass_color(c)}\\fad(0,300)" + "}" + rrect(rnd.uniform(18, 30), rnd.uniform(30, 46), 4)
              + "{\\p0}", 22)
    bubble(a, b, 540, 1530, "ยินดีด้วยครับ!", size=96, fill=RED, color=WHITE, border=RED_D, delay=1.6)


CARD_IN, CARD_GAP, GRID_HOLD = 1.0, 0.75, 2.6


def customer_timing(a, n):
    """Start time of each photo card and of the closing grid, for n real photos."""
    starts = [a + CARD_IN + CARD_GAP * k for k in range(n)]
    grid_t = a + CARD_IN + CARD_GAP * n + 0.5
    return starts, grid_t


def customers_duration(n):
    return CARD_IN + CARD_GAP * n + 0.5 + GRID_HOLD if n else 4.4


def scene_customers(a, b, photos):
    text(a, b, 540, 330, "และนี่คือ", size=72, color=GREY, delay=0.1)
    bubble(a, b, 540, 470, "ตัวอย่างลูกค้าของเรา", size=84, fill=RED, color=WHITE, border=RED_D, delay=0.3)
    if photos:
        starts, grid_t = customer_timing(a, len(photos))
        for st in starts:
            SFX.append((st, "whoosh"))
        for k in range(len(photos)):
            SFX.append((grid_t + 0.08 * k, "pop"))
        bubble(a, b, 540, 1720, "ขอบคุณลูกค้าทุกท่านที่ไว้วางใจ", size=56, delay=grid_t - a + 0.6, border=LIME, sfx=False)
        return
    frames = [(90, 640, -6), (560, 700, 5), (300, 1130, -2)]
    for i, (x, y, rot) in enumerate(frames):
        d = 0.6 + 0.35 * i
        sc.ev(a + d, b, "{" + f"\\an7\\pos({x + 12},{y + 16})\\frz{rot}\\p1\\bord0\\shad0\\blur8\\1c&H000000&\\1a&HB0&"
              "\\fad(150,150)" + "}" + rrect(430, 470, 12) + "{\\p0}", 9)
        sc.ev(a + d, b, "{" + f"\\an7\\pos({x},{y})\\frz{rot}\\p1\\bord5\\shad0\\1c&HFFFFFF&\\3c{ass_color(INK)}"
              "\\fad(150,150)" + "}" + rrect(430, 470, 12) + "{\\p0}", 10)
        if not photos:   # illustration inside the polaroid
            cols = [(BLUE, RED), (TEAL, GOLD), (RED, LIME)][i]
            sc.ev(a + d, b, "{" + f"\\an7\\pos({x + 25},{y + 25})\\frz{rot}\\p1\\bord0\\shad0\\1c{ass_color('#DDEFF7')}"
                  "\\fad(150,150)" + "}" + rrect(380, 330, 6) + "{\\p0}", 11)
            for j, c in enumerate(cols):
                for dx, dy, path, fill, *kw in person(c, s=0.62):
                    sc.ev(a + d, b, "{" + f"\\an7\\pos({x + 110 + j * 120 + dx:.0f},{y + 120 + dy:.0f})\\frz{rot}"
                          f"\\p1\\bord0\\shad0\\1c{ass_color(fill)}\\fad(150,150)" + "}" + path + "{\\p0}", 12)
        SFX.append((a + d, "pop"))
    if not photos:
        sc.label(a + 1.6, b, "ภาพประกอบ", x=60, y=1640)


def scene_outro(a, b):
    t1 = a + 3.2
    text(a, t1, 540, 560, "กว่าจะมาถึงวันโอน", size=84, color=INK, delay=0.1)
    bubble(a, t1, 540, 720, "มีอีกหลายขั้นตอน", size=88, fill=RED, color=WHITE, border=RED_D, delay=0.5)
    # path of steps leading to the house
    for i in range(5):
        shape(a, t1, 160 + i * 150, 1150 - i * 60, circle(70), [LGREY, LGREY, LGREY, LIME, RED][i], layer=6,
              anim="rise", delay=0.9 + 0.12 * i)
        text(a, t1, 195 + i * 150, 1185 - i * 60, "?" if i < 3 else "", size=44, color=GREY, delay=0.9 + 0.12 * i,
             layer=8)
    group(a, t1, 780, 820, house(0.6), anim="rise", delay=1.6, layer=8)
    bubble(a, t1, 540, 1480, "ก่อนวันโอน ต้องทำอะไรบ้าง?", size=66, delay=2.0, border=LIME)
    # CTA
    text(t1, b, 540, 520, "คลิปต่อไป", size=96, color=INK, delay=0.1)
    text(t1, b, 540, 640, "มาดูกันครับ!", size=80, color=RED, delay=0.3)
    for i, (label, col) in enumerate((("กดไลก์", RED), ("กดแชร์", LIME))):
        x = 330 + i * 420
        d = 0.6 + 0.3 * i
        sc.ev(t1 + d, b, "{" + f"\\an5\\pos({x},930)\\p1\\bord6\\shad0\\1c{ass_color(col)}\\3c{ass_color(INK)}"
              f"\\fscx10\\fscy10\\t({0},{200},\\fscx110\\fscy110)\\t(200,280,\\fscx100\\fscy100)"
              f"\\t(900,1050,\\fscx115\\fscy115)\\t(1050,1200,\\fscx100\\fscy100)\\fad(0,150)" + "}" + circle(230) + "{\\p0}", 20)
        icon = (poly([(0, 60), (40, 60), (40, 150), (0, 150)]) + " " +
                poly([(50, 60), (90, 0), (110, 10), (100, 55), (150, 55), (160, 75), (140, 150), (50, 150)])
                if i == 0 else poly([(0, 60), (100, 60), (100, 20), (170, 85), (100, 150), (100, 110), (0, 110)]))
        sc.ev(t1 + d, b, "{" + f"\\an5\\pos({x},925)\\p1\\bord0\\shad0\\1c&HFFFFFF&"
              f"\\fscx10\\fscy10\\t(0,200,\\fscx100\\fscy100)\\fad(0,150)" + "}" + icon + "{\\p0}", 21)
        text(t1, b, x, 1120, label, size=64, color=INK, delay=d + 0.1)
        SFX.append((t1 + d, "pop"))
    text(t1, b, 540, 1280, "แล้วพบกันคลิปหน้า", size=58, color=GREY, delay=1.3)


SCENES = [(scene_intro, 4.0), (scene_location, 4.2), (scene_queue, 4.8), (scene_call, 4.0), (scene_sign, 4.6),
          (scene_pay, 4.4), (scene_check_back, 4.4), (scene_keys, 4.2), (scene_receive, 4.6), (scene_photo, 4.4),
          (scene_customers, 4.4), (scene_outro, 7.0)]


def make_cards(photos, work):
    """Polaroid card (photo keeps its aspect ratio — nobody gets cropped out) + square grid thumbnail per photo."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    rnd = random.Random(7)
    cards, thumbs = [], []
    for k, ph in enumerate(photos):
        im = ImageOps.exif_transpose(Image.open(ph)).convert("RGB")
        s = min(760 / im.width, 880 / im.height)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        bw, bb = 26, 26
        card = Image.new("RGB", (im.width + 2 * bw, im.height + bw + bb), "white")
        card.paste(im, (bw, bw))
        m = 40
        canvas = Image.new("RGBA", (card.width + 2 * m, card.height + 2 * m), (0, 0, 0, 0))
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle((m + 10, m + 16, m + card.width + 10, m + card.height + 16), fill=(0, 0, 0, 110))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
        canvas.paste(card, (m, m))
        canvas = canvas.rotate(rnd.uniform(-5, 5) * (1 if k % 2 else -1), resample=Image.BICUBIC, expand=True)
        cp = work / f"card_{k}.png"
        canvas.save(cp)
        cards.append((cp, canvas.width, canvas.height))
        # grid thumbnail: square, centred slightly above the middle (faces are usually in the upper half)
        side = min(im.width, im.height)
        top = max(0, int((im.height - side) * 0.35))
        left = (im.width - side) // 2
        th = im.crop((left, top, left + side, top + side)).resize((282, 282), Image.LANCZOS)
        tcard = Image.new("RGB", (302, 302), "white")
        tcard.paste(th, (10, 10))
        tc = Image.new("RGBA", (342, 342), (0, 0, 0, 0))
        sh = Image.new("RGBA", tc.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((26, 30, 326, 330), fill=(0, 0, 0, 90))
        tc.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        tc.paste(tcard, (20, 20))
        tc = tc.rotate(rnd.uniform(-3, 3), resample=Image.BICUBIC, expand=True)
        tp = work / f"thumb_{k}.png"
        tc.save(tp)
        thumbs.append((tp, tc.width, tc.height))
    return cards, thumbs


def music(dur, sr=48000):
    """Bright, light background track generated here (royalty-free): I–V–vi–IV plucks + soft kick, 112 bpm."""
    t = np.arange(int(dur * sr)) / sr
    out = np.zeros_like(t, dtype=np.float32)
    beat = 60 / 112
    prog = [(261.6, 329.6, 392.0), (196.0, 246.9, 293.7), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6)]
    n_beats = int(dur / beat) + 1
    for k in range(n_beats):
        ch = prog[(k // 4) % 4]
        s0 = int(k * beat * sr)
        seg = min(len(t) - s0, int(beat * sr * 1.5))
        if seg <= 0:
            break
        tt = np.arange(seg) / sr
        env = np.exp(-tt * 5)
        note = ch[[0, 1, 2, 1][k % 4]] * 2
        out[s0:s0 + seg] += 0.16 * env * np.sin(2 * math.pi * note * tt) + 0.05 * env * np.sin(4 * math.pi * note * tt)
        pad = sum(np.sin(2 * math.pi * f * tt) for f in ch) * 0.025 * np.minimum(1, tt * 8) * np.exp(-tt * 1.2)
        out[s0:s0 + seg] += pad
        kick = np.sin(2 * math.pi * (55 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 14)
        out[s0:s0 + seg] += 0.22 * kick * (k % 2 == 0)
    fade = np.minimum(1, t / 0.6) * np.clip((dur - t) / 1.5, 0, 1)
    out *= fade
    return out / (np.abs(out).max() + 1e-9) * 0.45


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--photo", action="append", default=[])
    a = ap.parse_args()
    work = Path(a.out).resolve().parent / "_anim_work"
    work.mkdir(parents=True, exist_ok=True)
    t = 0.0
    cuts = []
    photos = a.photo[:9]
    cust_start = None
    for fn, dur in SCENES:
        if fn is scene_customers:
            dur = customers_duration(len(photos))
            cust_start = t
            fn(t, t + dur, photos)
            t += dur
            cuts.append(t)
            continue
        fn(t, t + dur)
        t += dur
        cuts.append(t)
    total = t
    for c in cuts[:-1]:
        wipe(c)
    (work / "anim.ass").write_text(sc.document(), encoding="utf-8")

    sr = 48000
    track = music(total, sr)
    bank = {k: synth_sfx(k, sr) for k in ("pop", "whoosh", "hit")}
    gain = {"pop": 0.18, "whoosh": 0.22, "hit": 0.3}
    for at, kind in SFX:
        i0 = int(max(0, at) * sr)
        x = bank[kind][: max(0, len(track) - i0)] * gain[kind]
        track[i0:i0 + len(x)] += x
    media.save_wav(work / "audio.wav", np.clip(track, -0.95, 0.95), sr)

    inputs = ["-f", "lavfi", "-i", f"color=c={BG.replace('#', '0x')}:s={W}x{H}:r={FPS}:d={total:.3f}"]
    sp_in, sp_g, base, idx = sprite_graph("0:v", 1)
    inputs += sp_in
    fc = f"[0:v]null[bg0]{sp_g.replace('[0:v][sp', '[bg0][sp')};[{base if base != '0:v' else 'bg0'}]" \
         f"ass=anim.ass:fontsdir={os.path.relpath(FONTS_DIR, work)}[v0]"
    # customer photos go into the polaroids (under the frames' white border is fine: drawn after ass? no — before)
    if photos:
        cards, thumbs = make_cards(photos, work)
        starts, grid_t = customer_timing(cust_start, len(photos))
        end = cust_start + customers_duration(len(photos))
        pre, cur = f"[0:v]null[bg0]{sp_g.replace('[0:v][sp', '[bg0][sp')}", (base if base != "0:v" else "bg0")
        for k, ((cp, cw, ch), st) in enumerate(zip(cards, starts)):
            inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(cp)]
            xc, yc = (W - cw) / 2, max(560, 1150 - ch / 2)
            x0 = -cw if k % 2 == 0 else W
            e = f"min(1,max(0,(t-{st:.3f})/0.42))"
            xe = f"{xc:.0f}+({x0:.0f}-{xc:.0f})*pow(1-{e},3)"
            ye = f"{yc:.0f}+90*pow(1-{e},3)"
            pre += (f";[{idx}:v]format=rgba,fade=t=in:st={st:.3f}:d=0.12:alpha=1[c{k}];"
                    f"[{cur}][c{k}]overlay=x='{xe}':y='{ye}':enable='between(t,{st:.3f},{grid_t:.3f})'[b{k + 1}]")
            cur = f"b{k + 1}"
            idx += 1
        n = len(thumbs)
        cols = 3 if n > 4 else 2
        rows = -(-n // cols)
        for k, (tp, tw, th_) in enumerate(thumbs):
            r, c = divmod(k, cols)
            in_row = min(cols, n - r * cols)          # centre a short last row
            cx = W / 2 + (c - (in_row - 1) / 2) * 330
            cy = 1080 + (r - (rows - 1) / 2) * 330
            tk = grid_t + 0.08 * k
            inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(tp)]
            pre += (f";[{idx}:v]format=rgba,fade=t=in:st={tk:.3f}:d=0.18:alpha=1[t{k}];"
                    f"[{cur}][t{k}]overlay={cx - tw / 2:.0f}:{cy - th_ / 2:.0f}:enable='between(t,{tk:.3f},{end:.3f})'[g{k}]")
            cur = f"g{k}"
            idx += 1
        fc = pre + f";[{cur}]ass=anim.ass:fontsdir={os.path.relpath(FONTS_DIR, work)}[v0]"
    logo = ROOT / "assets/brand/redrabbit_logo_red.png"
    inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(logo)]
    end_t = total - 3.8 + 1.6
    fc += (f";[{idx}:v]crop=2200:1300:780:1250,scale=520:-1,format=rgba,fade=t=in:st={end_t:.2f}:d=0.4:alpha=1[lg];"
           f"[v0][lg]overlay=(W-w)/2:1440:enable='gte(t,{end_t:.2f})'[v]")
    idx += 1
    inputs += ["-i", str(work / "audio.wav")]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[v]",
           "-map", f"{idx}:a", "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "18",
           "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
           "-t", f"{total:.3f}", str(Path(a.out).resolve())]
    subprocess.run(cmd, check=True, cwd=work)
    print(f"wrote {a.out} ({total:.1f}s, {len(SCENES)} scenes)")


if __name__ == "__main__":
    main()
