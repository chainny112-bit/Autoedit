"""Command-line runner.

  python cli.py VIDEO [--srt FILE] [--preset redrabbit_signature] [--density 3] [--mode auto] [--intensity high]
                [--asset FILE ...] [--ref IMG ...] [--music FILE] [--preview] [--variations clean,cinematic,retention]
"""
import argparse
import json
import shutil
import sys

from engine import jobs, presets
from engine.env import capabilities


def main():
    ap = argparse.ArgumentParser(description="AutoEdit — ตัดต่อวิดีโอแนวตั้งอัตโนมัติ")
    ap.add_argument("video")
    ap.add_argument("--srt", help="ไฟล์ซับ .srt/.vtt (ใช้แทน Speech-to-Text)")
    ap.add_argument("--preset", default="redrabbit_signature", help="id ของ Preset (ดู --list-presets)")
    ap.add_argument("--mode", choices=["clean", "story", "retention", "mograph", "experimental", "auto"])
    ap.add_argument("--density", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--intensity", choices=["low", "medium", "high"])
    ap.add_argument("--asset", action="append", default=[], help="ภาพ/วิดีโอประกอบ (ตั้งชื่อไฟล์ตามเนื้อหา)")
    ap.add_argument("--stock", action="append", default=[], help="Stock footage ที่มีสิทธิ์ใช้งาน")
    ap.add_argument("--ref", action="append", default=[], help="ภาพอ้างอิงสไตล์")
    ap.add_argument("--music", help="ไฟล์เพลงที่มีสิทธิ์ใช้งาน")
    ap.add_argument("--settings", help="JSON ของค่าตั้งค่าเพิ่มเติม")
    ap.add_argument("--preview", action="store_true", help="เรนเดอร์ Preview ความละเอียดครึ่งหนึ่ง")
    ap.add_argument("--plan-only", action="store_true", help="วิเคราะห์และสร้าง Editing Plan เท่านั้น")
    ap.add_argument("--variations", help="สร้างหลายเวอร์ชัน เช่น clean,cinematic,retention,creative,auto")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("-o", "--out", help="คัดลอกผลลัพธ์ (เวอร์ชันหลัก) ไปไว้ที่นี่")
    a = ap.parse_args()
    if a.list_presets:
        for p in presets.list_all():
            print(f"{p['id']:28s} {p['name']}")
        return
    caps = capabilities()
    if not caps["ready"]:
        sys.exit("เครื่องมือที่จำเป็นไม่ครบ: " + json.dumps({k: v for k, v in caps.items() if isinstance(v, dict) and not v["ok"]}, ensure_ascii=False))
    pre = presets.get(a.preset)
    if not pre:
        sys.exit(f"ไม่พบ Preset '{a.preset}'")
    settings = presets.to_settings(pre)
    settings.update(json.loads(a.settings) if a.settings else {})
    for k in ("mode", "density", "intensity"):
        if getattr(a, k):
            settings[k] = getattr(a, k)
    if a.music:
        settings["music"] = "upload"
    with open(a.video, "rb") as f:
        job = jobs.create(a.video, f, settings, preset_id=a.preset)
    jid = job["id"]
    for path, role, src in ([(a.srt, "transcript", "user")] if a.srt else []) + [(p, "broll", "user") for p in a.asset] + \
            [(p, "broll", "stock") for p in a.stock] + [(p, "reference", "user") for p in a.ref] + \
            ([(a.music, "music", "user")] if a.music else []):
        with open(path, "rb") as f:
            jobs.add_asset(jid, path, f, role, source=src)
    print("job", jid)
    jobs.run(jid, "analyze")
    j = jobs.get(jid)
    if j["status"] == "error" or j["variants"]["main"]["status"] == "error":
        sys.exit(1)
    print("AI Director:", (j["variants"]["main"].get("direction") or {}).get("summary", ""))
    vids = ["main"]
    if a.variations:
        vids += jobs.add_variations(jid, [k.strip() for k in a.variations.split(",") if k.strip()])
        for v in vids[1:]:
            if v == "creative":
                jobs.plan_creative_avoid(jid)
            jobs.run(jid, "plan", v)
    if a.plan_only:
        for v in vids:
            print(v, jobs.job_dir(jid) / "variants" / v / "plan.json")
        return
    for v in vids:
        jobs.run(jid, "preview" if a.preview else "render", v)
        j = jobs.get(jid)
        x = j["variants"][v]
        if x["status"] == "error":
            print(v, "ERROR", x["message"])
            continue
        out = x["outputs"]["preview" if a.preview else "final"]
        print(f"[{v}] {x['name']}: {jobs.job_dir(jid) / out['file']}  ({out['duration']:.1f}s, {out['seconds']}s render)")
        for i in out["qc"]:
            if i["level"] != "info":
                print(f"   QC [{i['level']}] {i['message']}")
    if a.out:
        key = "preview" if a.preview else "final"
        shutil.copy(jobs.job_dir(jid) / jobs.get(jid)["variants"]["main"]["outputs"][key]["file"], a.out)
        print("output:", a.out)


if __name__ == "__main__":
    main()
