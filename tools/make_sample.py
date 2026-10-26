"""Build a synthetic test clip: landscape talking-head + Thai TTS speech + matching SRT.

The speech deliberately contains long pauses, a filler word and a repeated
false-start sentence so the auto-cut logic has something to remove.
Face image: skimage.data.astronaut() (NASA, public domain).
"""
import subprocess, sys, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from skimage import data

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else "story"
OUT.mkdir(parents=True, exist_ok=True)
tmp = OUT / "_tmp"; tmp.mkdir(exist_ok=True)

# (text, pause_after_seconds)
LINES = [
    ("รู้ไหมว่า มีเกาะแห่งหนึ่ง ที่คนหายไปทั้งหมู่บ้าน ในคืนเดียว", 0.4),
    ("เอ่อ", 1.6),
    ("เรื่องนี้เกิดขึ้นเมื่อปี 1930", 0.3),
    ("เรื่องนี้เกิดขึ้นเมื่อปี 1930 ที่ทะเลสาบอันจิกุนี ในแคนาดา", 1.4),
    ("มีชาวบ้านอาศัยอยู่ประมาณ 30 คน", 0.5),
    ("แต่เมื่อนักล่าสัตว์เดินทางมาถึง กลับไม่พบใครเลยแม้แต่คนเดียว", 2.2),
    ("สิ่งที่น่าแปลกที่สุดคือ อาหารยังวางอยู่บนเตา และปืนยังแขวนอยู่ที่ผนัง", 0.5),
    ("ขั้นแรก ตำรวจตรวจสอบบ้านทุกหลัง ขั้นที่สอง ค้นหารอบทะเลสาบ ขั้นสุดท้าย สอบถามหมู่บ้านใกล้เคียง", 1.2),
    ("แต่จนถึงวันนี้ ยังไม่มีใครอธิบายได้ว่าเกิดอะไรขึ้น", 0.6),
    ("คุณคิดว่าพวกเขาหายไปไหน คอมเมนต์บอกกันได้เลย", 0.8),
]
BUSINESS = [
    ("วันนี้จะมาบอก 3 เคล็ดลับ ทำการตลาดออนไลน์ให้ยอดขายโต", 0.5),
    ("ปีที่แล้วร้านของเรามียอดขาย 120 ล้านบาท ปีนี้เพิ่มเป็น 180 ล้านบาท", 1.3),
    ("เอ่อ", 1.2),
    ("ข้อแรก ต้องรู้จักลูกค้า ข้อที่สอง ทำคอนเทนต์สม่ำเสมอ ข้อที่สาม วัดผลทุกแคมเปญ", 0.6),
    ("ลองเปิดแอปแล้วดูสถิติของเพจ จะเห็นว่าคนดูเพิ่มขึ้น 45 เปอร์เซ็นต์", 1.6),
    ("สรุปคือ ทำทีละขั้น แล้วผลลัพธ์จะตามมา ทักมาปรึกษาเราได้เลย", 0.8),
]
if SCRIPT == "business":
    LINES = BUSINESS
SR = 48000
audio = [np.zeros(int(0.6 * SR), np.int16)]
cues, t = [], 0.6
for i, (text, pause) in enumerate(LINES):
    wav = tmp / f"l{i}.wav"
    subprocess.run(["espeak-ng", "-v", "th", "-s", "150", "-w", str(wav), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ar", str(SR), "-ac", "1", str(wav) + ".r.wav"], check=True)
    with wave.open(str(wav) + ".r.wav") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    # trim espeak's own leading/trailing silence so SRT timing is tight
    nz = np.nonzero(np.abs(pcm) > 300)[0]
    pcm = pcm[max(0, nz[0] - 480): nz[-1] + 960]
    d = len(pcm) / SR
    cues.append((t, t + d, text))
    audio += [pcm, np.zeros(int(pause * SR), np.int16)]
    t += d + pause
pcm = np.concatenate(audio)
# light room noise so the denoiser has work to do
pcm = np.clip(pcm.astype(np.float32) + np.random.normal(0, 120, len(pcm)), -32768, 32767).astype(np.int16)
PREFIX = "" if SCRIPT == "story" else SCRIPT + "_"
with wave.open(str(OUT / f"{PREFIX}sample_voice.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
dur = len(pcm) / SR

def ts(s):
    ms = int(round(s * 1000)); return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"
(OUT / f"{PREFIX}sample.srt").write_text("".join(f"{i+1}\n{ts(a)} --> {ts(b)}\n{x}\n\n" for i, (a, b, x) in enumerate(cues)), encoding="utf-8")

# landscape frame: dark studio background, presenter placed right of centre
bg = Image.new("RGB", (1920, 1080))
grad = np.linspace(30, 70, 1920)[None, :, None] * np.array([1.0, 0.85, 0.7])
bg = Image.fromarray(np.repeat(grad, 1080, 0).astype(np.uint8))
face = Image.fromarray(data.astronaut()).resize((900, 900))
bg.paste(face, (1100, 140))
bg = bg.filter(ImageFilter.GaussianBlur(0.6))
bg.save(tmp / "frame.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(tmp / "frame.png"),
                "-i", str(OUT / f"{PREFIX}sample_voice.wav"),
                "-vf", "scale=2112:1188,crop=1920:1080:'96+40*sin(t/3)':'54+20*sin(t/4)',format=yuv420p",
                "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                "-shortest", str(OUT / f"{PREFIX}sample_talking_head.mp4")], check=True)
print(f"wrote {OUT}/{PREFIX}sample_talking_head.mp4 ({dur:.1f}s) and {PREFIX}sample.srt")
