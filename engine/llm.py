"""Optional story analysis with Claude. Used only when an Anthropic credential is configured;
the heuristic planner works without it."""
import json
import os

ROLES = ["hook", "point", "example", "steps", "turn", "conclusion"]
BROLL = ["none", "stat", "steps", "timeline", "keyword", "compare", "atmosphere", "illustration"]

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "role": {"type": "string", "enum": ROLES},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "title_card": {"type": "string"},
                    "broll": {"type": "string", "enum": BROLL},
                    "broll_description": {"type": "string"},
                    "image_prompt": {"type": "string"},
                },
                "required": ["id", "role", "keywords", "title_card", "broll", "broll_description", "image_prompt"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "segments"],
    "additionalProperties": False,
}

PROMPT = """คุณเป็นบรรณาธิการวิดีโอสั้นแนวเล่าเรื่อง (TikTok/Reels) วิเคราะห์บทพูดภาษาไทยด้านล่าง ซึ่งแบ่งเป็นประโยคพร้อม id

สำหรับแต่ละประโยคให้ระบุ:
- role: hook (เปิดเรื่องดึงความสนใจ), point (ประเด็นหลัก), example (ตัวอย่าง), steps (ขั้นตอน), turn (จุดเปลี่ยน/หักมุม), conclusion (สรุป/ชวนคอมเมนต์)
- keywords: 0-2 คำที่ควรเน้นสีในซับ ต้องเป็นคำที่ปรากฏในประโยคนั้นตรงตัวอักษร
- title_card: ข้อความสั้นไม่เกิน 20 ตัวอักษร สำหรับ Title Card เฉพาะประโยคที่สำคัญมาก (hook หรือจุดเปลี่ยนใหญ่) ที่เหลือให้เป็นสตริงว่าง ต้องสอดคล้องกับสิ่งที่พูดจริง ห้ามแต่งข้อเท็จจริงใหม่
- broll: ประเภทภาพประกอบที่ช่วยอธิบาย (none ถ้าควรเห็นหน้าผู้พูด) ใช้อย่างพอดี ไม่เกินครึ่งหนึ่งของประโยค
- broll_description: อธิบายภาพที่ต้องใช้เป็นภาษาไทยสั้นๆ (ว่างถ้า none)
- image_prompt: prompt ภาษาอังกฤษสำหรับสร้างภาพประกอบ (ว่างถ้าไม่ต้องใช้ภาพ) โทนมืด แสงสีแดงเข้ม cinematic ห้ามทำให้ดูเหมือนภาพหลักฐานจริง

บทพูด:
"""


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def analyze(segments, log=print):
    import anthropic

    client = anthropic.Anthropic()
    lines = "\n".join(f'{s["id"]}: {s["text"]}' for s in segments if s["keep"])
    kwargs = dict(
        model=os.environ.get("AUTOEDIT_CLAUDE_MODEL", "claude-opus-5-5"),
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT + lines}],
    )
    try:
        # server-side fallback model if the primary declines (refusal)
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except TypeError:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude ปฏิเสธคำขอวิเคราะห์ — ใช้การวิเคราะห์แบบ heuristic แทน")
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    log(f"Claude วิเคราะห์โครงเรื่องแล้ว: {data.get('summary', '')[:120]}")
    return {s["id"]: s for s in data["segments"]}, data.get("summary", "")
