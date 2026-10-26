"""Face tracking and scene-cut detection on sampled frames."""
import subprocess

import numpy as np

from . import MODELS_DIR

try:
    import cv2
    HAVE_CV2 = True
except Exception:  # pragma: no cover
    HAVE_CV2 = False

YUNET = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
HAAR_FRONT = MODELS_DIR / "haarcascade_frontalface_default.xml"
HAAR_PROFILE = MODELS_DIR / "haarcascade_profileface.xml"


def detector_name():
    if not HAVE_CV2:
        return None
    if YUNET.exists() and YUNET.stat().st_size > 10000 and hasattr(cv2, "FaceDetectorYN"):
        return "yunet"
    if HAAR_FRONT.exists() and hasattr(cv2, "CascadeClassifier"):
        return "haar"
    return None


class _Detector:
    def __init__(self, w, h):
        self.kind = detector_name()
        if self.kind == "yunet":
            self.d = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.75)
        elif self.kind == "haar":
            self.front = cv2.CascadeClassifier(str(HAAR_FRONT))
            self.prof = cv2.CascadeClassifier(str(HAAR_PROFILE)) if HAAR_PROFILE.exists() else None

    def __call__(self, bgr):
        if self.kind == "yunet":
            _, faces = self.d.detect(bgr)
            return [] if faces is None else [tuple(map(float, f[:4])) for f in faces]
        if self.kind == "haar":
            g = cv2.equalizeHist(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
            minsz = max(24, g.shape[0] // 12)
            f = list(self.front.detectMultiScale(g, 1.1, 5, minSize=(minsz, minsz)))
            if not f and self.prof is not None:
                f = list(self.prof.detectMultiScale(g, 1.1, 5, minSize=(minsz, minsz)))
                if not f:  # profile cascade only knows one side; try mirrored
                    gm = cv2.flip(g, 1)
                    f = [(g.shape[1] - x - w, y, w, h) for x, y, w, h in self.prof.detectMultiScale(gm, 1.1, 5, minSize=(minsz, minsz))]
            return [tuple(map(float, b)) for b in f]
        return []


def analyze(video, info, sample_fps=2.0, log=print):
    """Return {"samples": [{"t", "face": [cx, cy, w, h] normalised or None}], "scene_cuts": [t...]}."""
    if not detector_name():
        log("⚠️ ไม่มีตัวตรวจจับใบหน้า (OpenCV/โมเดล) — จะใช้การครอปกึ่งกลางแทน")
    W = 480
    H = int(round(info["height"] * W / info["width"] / 2) * 2)
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video), "-an",
           "-vf", f"fps={sample_fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    det = _Detector(W, H) if detector_name() else None
    frame_bytes = W * H * 3
    samples, cuts, prev_hist, k = [], [], None, 0
    while True:
        buf = p.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        t = k / sample_fps
        face = None
        if det:
            boxes = det(img)
            if boxes:
                x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
                face = [round((x + w / 2) / W, 4), round((y + h / 2) / H, 4), round(w / W, 4), round(h / H, 4)]
        samples.append({"t": round(t, 2), "face": face})
        small = img[::4, ::4].astype(np.int16)
        hist = np.concatenate([np.histogram(small[..., c], 16, (0, 256))[0] for c in range(3)]).astype(np.float32)
        hist /= hist.sum() + 1e-6
        if prev_hist is not None and np.abs(hist - prev_hist).sum() > 0.5:
            cuts.append(round(t, 2))
        prev_hist = hist
        k += 1
    p.wait()
    found = sum(1 for s in samples if s["face"])
    log(f"ตรวจจับใบหน้า ({detector_name() or 'none'}): พบ {found}/{len(samples)} เฟรมตัวอย่าง, ฉากเปลี่ยน {len(cuts)} จุด")
    return {"samples": samples, "scene_cuts": cuts, "detector": detector_name(), "sample_fps": sample_fps}


def face_in_range(vis, t0, t1):
    """Median face box over [t0, t1]; None if the face is absent in most samples."""
    if not vis:
        return None
    ss = [s for s in vis["samples"] if t0 - 0.25 <= s["t"] <= t1 + 0.25]
    if not ss:
        return None
    faces = [s["face"] for s in ss if s["face"]]
    if len(faces) < max(1, len(ss) * 0.4):
        # fall back to the nearest detection within 3 s (speaker briefly turned away)
        near = [s for s in vis["samples"] if s["face"] and abs(s["t"] - (t0 + t1) / 2) < 3]
        if not near:
            return None
        faces = [min(near, key=lambda s: abs(s["t"] - (t0 + t1) / 2))["face"]]
    arr = np.array(faces)
    return [round(float(v), 4) for v in np.median(arr, 0)]


def global_face(vis):
    faces = [s["face"] for s in (vis or {}).get("samples", []) if s["face"]]
    if not faces:
        return None
    return [round(float(v), 4) for v in np.median(np.array(faces), 0)]
