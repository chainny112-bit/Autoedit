"""Detects which tools/services are available so the UI can warn and the pipeline can degrade."""
import os

from . import FONTS_DIR, llm, media, transcribe, vision


def _install_hint():
    import sys
    if sys.platform == "darwin":
        return "บน Mac ให้รัน: brew install ffmpeg-full แล้วเปิดโปรแกรมใหม่ (ระบบจะใช้ ffmpeg-full ให้เอง)"
    if sys.platform.startswith("win"):
        return "ใช้ FFmpeg รุ่น full จาก gyan.dev หรือ BtbN แล้วเพิ่มโฟลเดอร์ bin เข้า PATH"
    return "ติดตั้ง ffmpeg ที่มี libass/libx264 (เช่น apt install ffmpeg)"


def capabilities():
    tv = media.tool_versions()
    ff = tv.get("ffmpeg", {})
    try:
        import pythainlp  # noqa: F401
        thai_nlp = True
    except Exception:
        thai_nlp = False
    fonts = sorted(p.name for p in FONTS_DIR.glob("*.ttf"))
    missing = [n for n, k in (("libass (ซับ/กราฟิก)", "libass"), ("libx264 (H.264)", "libx264"), ("aac (เสียง)", "aac"))
               if ff.get("path") and not ff.get(k)]
    if not ff.get("path"):
        ff_detail = "ไม่พบ ffmpeg — " + _install_hint()
    elif missing:
        ff_detail = f"{ff.get('path')}: ขาด {', '.join(missing)} — {_install_hint()}"
    else:
        ff_detail = f"{ff.get('version', '')} ({ff.get('path')})"
    caps = {
        "ffmpeg": {"ok": bool(ff.get("path")) and not missing, "detail": ff_detail, "required": True},
        "ffprobe": {"ok": bool(tv.get("ffprobe", {}).get("path")), "detail": tv.get("ffprobe", {}).get("version", "ไม่พบ"),
                    "required": True},
        "fonts": {"ok": bool(fonts), "detail": ", ".join(fonts) or "ไม่พบฟอนต์ไทยใน assets/fonts", "required": True},
        "speech_to_text": {"ok": transcribe.whisper_available(),
                           "detail": "faster-whisper (ดาวน์โหลดโมเดลจาก HuggingFace ครั้งแรก)" if transcribe.whisper_available()
                           else "ไม่ได้ติดตั้ง faster-whisper — ต้องแนบไฟล์ซับ .srt/.vtt", "required": False},
        "face_detection": {"ok": bool(vision.detector_name()), "detail": vision.detector_name() or "ไม่มี OpenCV — ใช้ครอปกึ่งกลาง",
                           "required": False},
        "thai_nlp": {"ok": thai_nlp, "detail": "PyThaiNLP (ตัดคำ/ตรวจคำ)" if thai_nlp else "ไม่มี PyThaiNLP — ตัดคำแบบพื้นฐาน",
                     "required": False},
        "llm_story_analysis": {"ok": llm.available(), "detail": "Claude API" if llm.available()
                               else "ไม่มี ANTHROPIC_API_KEY — ใช้การวิเคราะห์แบบกฎ (heuristic)", "required": False},
        "ai_image": {"ok": bool(os.environ.get("AUTOEDIT_IMAGE_CMD")),
                     "detail": "AUTOEDIT_IMAGE_CMD ตั้งค่าแล้ว" if os.environ.get("AUTOEDIT_IMAGE_CMD")
                     else "ไม่ได้ตั้งค่าตัวสร้างภาพ AI — ใช้ Placeholder + ภาพที่อัปโหลด", "required": False},
    }
    caps["ready"] = all(v["ok"] for v in caps.values() if isinstance(v, dict) and v.get("required"))
    return caps
