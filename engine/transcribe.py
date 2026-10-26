"""Speech-to-text with word timestamps (faster-whisper), or import of SRT/VTT transcripts.

Whatever the source, output is a list of segments:
  {"id", "start", "end", "text", "words": [{"w", "s", "e"}], "word_level": bool}
where words are PyThaiNLP tokens (spaces kept as " " tokens) carrying timings.
"""
import re
from pathlib import Path

import numpy as np

from . import thai


def whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe_whisper(wav_path, model_size="small", language="th", log=print, device="auto"):
    from faster_whisper import WhisperModel
    log(f"กำลังโหลดโมเดล faster-whisper '{model_size}' (ครั้งแรกจะดาวน์โหลดจาก HuggingFace)")
    try:
        model = WhisperModel(model_size, device=device, compute_type="int8")
    except Exception as e:
        raise RuntimeError(
            f"โหลดโมเดล Whisper '{model_size}' ไม่สำเร็จ: {e}\n"
            "ตรวจสอบการเชื่อมต่ออินเทอร์เน็ตไปยัง huggingface.co หรือแนบไฟล์ซับ .srt/.vtt แทน") from e
    segs, info = model.transcribe(str(wav_path), language=language or None, word_timestamps=True,
                                  vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
                                  condition_on_previous_text=False, beam_size=5)
    out = []
    for i, s in enumerate(segs):
        chars = []  # per-character (char, start, end) timeline from ASR word pieces
        for w in (s.words or []):
            txt = w.word
            n = max(1, len(txt))
            for k, c in enumerate(txt):
                chars.append((c, w.start + (w.end - w.start) * k / n, w.start + (w.end - w.start) * (k + 1) / n))
        text = s.text.strip()
        if not chars:
            chars = _linear_chars(text, s.start, s.end)
        out.append(_segment_from_chars(f"s{i}", chars, word_level=True))
        log(f"  [{s.start:6.2f}-{s.end:6.2f}] {text}")
    return out, {"language": info.language, "probability": round(info.language_probability, 3)}


def _ts(x):
    x = x.strip().replace(",", ".")
    parts = x.split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def parse_subtitles(path):
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for block in re.split(r"\n\s*\n", raw.replace("\r", "")):
        m = re.search(r"([\d:\.,]+)\s*-->\s*([\d:\.,]+)", block)
        if not m:
            continue
        lines = block[m.end():].strip().splitlines()
        text = " ".join(re.sub(r"<[^>]+>|\{[^}]+\}", "", l).strip() for l in lines if l.strip())
        if text:
            cues.append((_ts(m.group(1)), _ts(m.group(2)), text))
    if not cues:
        raise ValueError("ไม่พบคิวซับไตเติลในไฟล์ (รองรับ .srt / .vtt)")
    return cues


def _linear_chars(text, s, e, speech_mask=None):
    """Spread characters across [s, e]. If a speech mask is given, time only advances while voiced,
    so pauses inside a cue don't get words assigned to them."""
    vis = [c for c in text]
    n = max(1, len(vis))
    if speech_mask is None:
        return [(c, s + (e - s) * k / n, s + (e - s) * (k + 1) / n) for k, c in enumerate(vis)]
    mask, step = speech_mask
    i0, i1 = int(s / step), max(int(s / step) + 1, int(e / step))
    seg = mask[i0:i1]
    voiced_idx = np.nonzero(seg)[0]
    if len(voiced_idx) < 3:
        return _linear_chars(text, s, e)
    out = []
    for k, c in enumerate(vis):
        a = voiced_idx[min(len(voiced_idx) - 1, int(len(voiced_idx) * k / n))]
        b = voiced_idx[min(len(voiced_idx) - 1, int(len(voiced_idx) * (k + 1) / n) - 1 if k + 1 < n else len(voiced_idx) - 1)]
        out.append((c, (i0 + a) * step, (i0 + b + 1) * step))
    return out


def _segment_from_chars(sid, chars, word_level):
    text = "".join(c for c, _, _ in chars).strip()
    text = re.sub(r"\s+", " ", text)
    # align normalised text back onto char timeline (skip leading whitespace from ASR pieces)
    stream = [(c, a, b) for c, a, b in chars]
    while stream and stream[0][0].isspace():
        stream.pop(0)
    toks = thai.tokenize(text)
    words, pos = [], 0
    for t in toks:
        if t == " ":
            while pos < len(stream) and stream[pos][0].isspace():
                pos += 1
            words.append({"w": " ", "s": None, "e": None})
            continue
        # tokens may differ from raw chars only by collapsed whitespace
        while pos < len(stream) and stream[pos][0].isspace():
            pos += 1
        a = stream[min(pos, len(stream) - 1)][1] if stream else 0
        pos += len(t)
        b = stream[min(pos, len(stream)) - 1][2] if stream else 0
        words.append({"w": t, "s": round(a, 3), "e": round(max(b, a + 0.04), 3)})
    timed = [w for w in words if w["s"] is not None]
    start = timed[0]["s"] if timed else (chars[0][1] if chars else 0)
    end = timed[-1]["e"] if timed else (chars[-1][2] if chars else 0)
    return {"id": sid, "start": round(start, 3), "end": round(end, 3), "text": text, "words": words,
            "word_level": word_level}


def segments_from_subtitles(path, speech_mask=None):
    out = []
    for i, (s, e, text) in enumerate(parse_subtitles(path)):
        seg = _segment_from_chars(f"s{i}", _linear_chars(text, s, e, speech_mask), word_level=False)
        seg["start"], seg["end"] = round(s, 3), round(e, 3)
        out.append(seg)
    return out


def retime_text(seg, new_text, speech_mask=None):
    """User edited the words: keep the segment's time span, redistribute timings over the new text."""
    s = _segment_from_chars(seg["id"], _linear_chars(new_text, seg["start"], seg["end"], speech_mask),
                            word_level=False)
    s["start"], s["end"] = seg["start"], seg["end"]
    return s


def speech_mask_from_silences(silences, duration, step=0.02):
    n = int(duration / step) + 2
    mask = np.ones(n, bool)
    for a, b in silences:
        mask[int(a / step): int(b / step)] = False
    return mask, step
