"""Person segmentation (MediaPipe selfie multiclass) -> per-clip alpha mask videos with quality metrics."""
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import MODELS_DIR

MODEL_MULTI = MODELS_DIR / "selfie_multiclass_256x256.tflite"
MODEL_FAST = MODELS_DIR / "selfie_segmenter.tflite"
MW, MH = 288, 512   # mask resolution (9:16); upscaled + feathered when composited


@lru_cache(maxsize=1)
def status():
    """(available, detail). Checks the library, a model file and that the runtime actually loads."""
    try:
        import mediapipe as mp  # noqa: F401
        from mediapipe.tasks.python import BaseOptions, vision
    except Exception as e:
        return False, f"ไม่ได้ติดตั้ง mediapipe ({type(e).__name__})"
    model = MODEL_MULTI if MODEL_MULTI.exists() else MODEL_FAST if MODEL_FAST.exists() else None
    if not model:
        return False, "ไม่พบไฟล์โมเดล selfie segmenter ใน assets/models"
    try:
        seg = _make(model, image_mode=True)
        seg.segment(_mp_image(np.zeros((64, 64, 3), np.uint8)))
        seg.close()
    except Exception as e:
        return False, f"โหลด MediaPipe ไม่ได้: {str(e)[:120]} (Linux ต้องมี libegl1/libgles2)"
    return True, f"MediaPipe ({model.name})"


def _mp_image(rgb):
    import mediapipe as mp
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


def _make(model, image_mode=False):
    from mediapipe.tasks.python import BaseOptions, vision
    mode = vision.RunningMode.IMAGE if image_mode else vision.RunningMode.VIDEO
    opts = vision.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(model)),
                                        output_confidence_masks=True, running_mode=mode)
    return vision.ImageSegmenter.create_from_options(opts)


def _fg(res):
    cm = res.confidence_masks
    m = np.squeeze(cm[0].numpy_view()).astype(np.float32)
    return 1.0 - m if len(cm) > 1 else m   # multiclass: class 0 = background


def clip_mask(src, a, d, crop, fps, cache_dir, log=None):
    """Mask video (gray, MW x MH) for the cropped presenter region of a clip. Cached by content key."""
    import cv2
    ok, why = status()
    if not ok:
        return None, {"ok": False, "reason": why}
    model = MODEL_MULTI if MODEL_MULTI.exists() else MODEL_FAST
    st = Path(src).stat()
    key = hashlib.sha1(json.dumps([str(src), st.st_size, int(st.st_mtime), round(a, 3), round(d, 3), crop, fps,
                                   model.name, 2]).encode()).hexdigest()[:20]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out, meta_p = cache_dir / f"mask_{key}.mkv", cache_dir / f"mask_{key}.json"
    if out.exists() and meta_p.exists():
        return out, json.loads(meta_p.read_text())
    x, y, cw, ch = crop
    dec = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{a:.4f}", "-t",
                            f"{d:.4f}", "-i", str(src), "-vf", f"crop={cw}:{ch}:{x}:{y},scale={MW}:{MH},fps={fps}",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-f", "rawvideo",
                            "-pix_fmt", "gray", "-s", f"{MW}x{MH}", "-r", f"{fps}", "-i", "-", "-c:v", "ffv1",
                            str(out)], stdin=subprocess.PIPE)
    seg = _make(model)
    stride = 2 if fps > 20 else 1
    prev, shares, unc, ious, n = None, [], [], [], 0
    fb = MW * MH * 3
    kernel = np.ones((3, 3), np.uint8)
    while True:
        buf = dec.stdout.read(fb)
        if len(buf) < fb:
            break
        rgb = np.frombuffer(buf, np.uint8).reshape(MH, MW, 3)
        if prev is None or n % stride == 0:   # run the model every `stride` frames, reuse in between
            m = _fg(seg.segment_for_video(_mp_image(rgb), int(n * 1000 / fps)))
            if m.shape != (MH, MW):
                m = cv2.resize(m, (MW, MH))
            if prev is not None:
                m = 0.65 * m + 0.35 * prev      # temporal smoothing against flicker
        else:
            m = prev
        unc.append(float(((m > 0.2) & (m < 0.8)).mean()))
        hard = (m > 0.5).astype(np.uint8)
        # keep the main body (largest blobs); drop stray islands
        nlab, lab, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
        if nlab > 2:
            areas = stats[1:, cv2.CC_STAT_AREA]
            keep = 1 + np.nonzero(areas >= areas.max() * 0.15)[0]
            m = m * np.isin(lab, keep)
        hard = (m > 0.5)
        if prev is not None:
            ph = prev > 0.5
            inter, union = (hard & ph).sum(), (hard | ph).sum()
            ious.append(float(inter / union) if union else 1.0)
        shares.append(float(hard.mean()))
        prev = m
        alpha = np.clip((m - 0.35) / 0.3, 0, 1)
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, kernel)
        alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
        enc.stdin.write((alpha * 255).astype(np.uint8).tobytes())
        n += 1
    seg.close()
    dec.wait()
    enc.stdin.close()
    enc.wait()
    if n == 0 or enc.returncode != 0:
        return None, {"ok": False, "reason": "ถอดรหัสเฟรมเพื่อแยกตัวบุคคลไม่ได้"}
    meta = {"frames": n, "share": round(float(np.mean(shares)), 3), "share_std": round(float(np.std(shares)), 3),
            "uncertain": round(float(np.mean(unc)), 3), "iou": round(float(np.mean(ious)) if ious else 1.0, 3)}
    problems = []
    if not 0.04 < meta["share"] < 0.85:
        problems.append(f"สัดส่วนตัวบุคคลผิดปกติ ({meta['share']:.0%})")
    if meta["uncertain"] > 0.12:
        problems.append(f"ขอบไม่ชัด {meta['uncertain']:.0%}")
    if meta["iou"] < 0.85:
        problems.append(f"mask กระพริบ (IoU {meta['iou']:.2f})")
    meta["ok"] = not problems
    meta["reason"] = "; ".join(problems)
    meta_p.write_text(json.dumps(meta))
    return out, meta


def detect_chroma(src, info, t=None):
    """Fraction of border pixels that are chroma green/blue (a real green/blue screen)."""
    t = info["duration"] / 2 if t is None else t
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src),
                        "-frames:v", "1", "-vf", "scale=160:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    w = 160
    if not p.stdout:
        return {"green": 0.0, "blue": 0.0}
    h = len(p.stdout) // (w * 3)
    img = np.frombuffer(p.stdout[: w * h * 3], np.uint8).reshape(h, w, 3).astype(int)
    border = np.concatenate([img[:, :12].reshape(-1, 3), img[:, -12:].reshape(-1, 3), img[:8].reshape(-1, 3)])
    r, g, b = border[:, 0], border[:, 1], border[:, 2]
    green = ((g > 90) & (g > r * 1.35) & (g > b * 1.35)).mean()
    blue = ((b > 90) & (b > r * 1.35) & (b > g * 1.2)).mean()
    return {"green": round(float(green), 3), "blue": round(float(blue), 3)}
