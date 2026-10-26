"""FFmpeg/ffprobe helpers."""
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


class ToolError(RuntimeError):
    pass


def run(cmd, timeout=None, log=None):
    cmd = [str(c) for c in cmd]
    if log:
        log("$ " + " ".join(c if " " not in c else repr(c) for c in cmd)[:600])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise ToolError(f"{Path(cmd[0]).name} failed (exit {p.returncode}):\n{tail}")
    return p


def ffmpeg(*args, log=None, timeout=None):
    return run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args], timeout=timeout, log=log)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(p.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise ToolError("ไฟล์นี้ไม่มีสตรีมวิดีโอ")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = int(v.get("tags", {}).get("rotate", rot)) % 360
    if rot in (90, 270):
        w, h = h, w  # ffmpeg autorotates on decode
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    if not 1 <= fps <= 120:
        fps = 30.0
    dur = float(info["format"].get("duration") or v.get("duration") or 0)
    return {
        "path": str(path), "width": w, "height": h, "fps": round(fps, 3), "duration": dur,
        "orientation": "portrait" if h > w else ("square" if h == w else "landscape"),
        "has_audio": a is not None, "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name") if a else None,
        "sample_rate": int(a["sample_rate"]) if a else None,
    }


def extract_audio(src, dst, sr=16000, denoise=False, log=None):
    af = ["highpass=f=70", "lowpass=f=12000"]
    if denoise:
        af.append("afftdn=nr=12:nf=-40")
    ffmpeg("-i", src, "-vn", "-ac", "1", "-ar", sr, "-af", ",".join(af), "-c:a", "pcm_s16le", dst, log=log)
    return dst


def load_wav(path):
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            pcm = pcm.reshape(-1, w.getnchannels()).mean(1)
    return pcm, sr


def save_wav(path, pcm, sr):
    pcm = np.clip(pcm, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())


def detect_silences(wav_path, noise_db=-35, min_dur=0.3):
    """Silence intervals via ffmpeg silencedetect, threshold relative to the clip's speech level."""
    pcm, sr = load_wav(wav_path)
    # Adapt threshold: speech RMS 90th percentile minus 25 dB, bounded.
    hop = int(sr * 0.02)
    if len(pcm) > hop:
        frames = pcm[: len(pcm) // hop * hop].reshape(-1, hop)
        rms_db = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)
        noise_db = float(np.clip(np.percentile(rms_db, 90) - 25, -55, -25))
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(wav_path), "-af",
                        f"silencedetect=noise={noise_db:.1f}dB:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d\.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d\.]+)", p.stderr)]
    total = len(pcm) / sr
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else total
        out.append((max(0.0, s), e))
    return out, noise_db


def rms_envelope(pcm, sr, win=0.02):
    hop = max(1, int(sr * win))
    n = len(pcm) // hop
    if n == 0:
        return np.zeros(1), win
    fr = pcm[: n * hop].reshape(n, hop)
    return np.sqrt((fr ** 2).mean(1)), win


def thumbnail(src, t, dst, width=320, log=None):
    ffmpeg("-ss", f"{max(0, t):.3f}", "-i", src, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", dst, log=log)
    return dst


def tool_versions():
    out = {}
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        out[tool] = {"path": path}
        if path:
            p = subprocess.run([tool, "-version"], capture_output=True, text=True)
            out[tool]["version"] = p.stdout.splitlines()[0] if p.stdout else "?"
    if out["ffmpeg"]["path"]:
        f = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        e = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        out["ffmpeg"]["libass"] = bool(re.search(r"\sass\s", f))
        out["ffmpeg"]["libx264"] = "libx264" in e
        out["ffmpeg"]["aac"] = bool(re.search(r"\saac\s", e))
        out["ffmpeg"]["sidechaincompress"] = "sidechaincompress" in f
        out["ffmpeg"]["loudnorm"] = "loudnorm" in f
    return out
