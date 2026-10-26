"""AutoEdit engine: analysis, planning, motion graphics and rendering for vertical talking-head videos."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS_DIR = ASSETS / "fonts"
MODELS_DIR = ASSETS / "models"
DATA_DIR = ROOT / "data"


def _prefer_full_ffmpeg():
    """Homebrew's plain `ffmpeg` is a slim build without libass; the complete build is the keg-only `ffmpeg-full`,
    which is not on PATH by default. Put it (or AUTOEDIT_FFMPEG_DIR) first so every ffmpeg call uses it."""
    import os
    cands = [os.environ.get("AUTOEDIT_FFMPEG_DIR", ""), "/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"]
    for d in cands:
        if d and Path(d, "ffmpeg").exists() and Path(d, "ffprobe").exists():
            parts = os.environ.get("PATH", "").split(os.pathsep)
            if d not in parts:
                os.environ["PATH"] = os.pathsep.join([d] + parts)
            return d
    return None


FFMPEG_DIR = _prefer_full_ffmpeg()
