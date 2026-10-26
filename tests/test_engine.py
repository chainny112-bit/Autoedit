"""Fast unit tests (no rendering). Run: python3 -m pytest tests -q"""
from pathlib import Path

from engine import analyze as A, graphics as G, planner, render, thai, transcribe as T

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_tokenize_keeps_numbers_and_spaces():
    toks = thai.tokenize("มีชาวบ้าน 1,930 คน")
    assert "1,930" in toks and " " in toks


def test_phrases_fit_one_line():
    toks = thai.tokenize("แต่เมื่อนักล่าสัตว์เดินทางมาถึง กลับไม่พบใครเลยแม้แต่คนเดียว")
    for a, b in thai.chunk_phrases(toks, 16):
        assert thai.visual_len("".join(toks[a:b])) <= 20


def test_spelling_flags_only_suspicious_words():
    assert thai.unknown_words("ที่ทะเลสาบอันจิกุนี ในแคนาดา") == ["อันจิกุนี"]
    assert thai.unknown_words("แต่จนถึงวันนี้ ยังไม่มีใครอธิบายได้") == []


def _segments():
    return T.segments_from_subtitles(SAMPLES / "sample.srt")


def test_cuts_use_meaning_filler_and_false_start():
    segs = A.classify_cuts(_segments(), {}, log=lambda *_: None)
    by = {s["id"]: s for s in segs}
    assert not by["s1"]["keep"] and "ติดปาก" in by["s1"]["cut_reason"]          # "เอ่อ"
    assert not by["s2"]["keep"] and "ซ้ำ" in by["s2"]["cut_reason"]             # false start
    assert by["s3"]["keep"]                                                       # complete retake kept
    assert sum(s["keep"] for s in segs) == 8


def test_clips_never_overlap_or_cut_words():
    segs = A.classify_cuts(_segments(), {}, log=lambda *_: None)
    A.build_clips(segs, [], 70.0, {}, A.story_structure(segs))
    clips = [c for s in segs for c in s["clips"]]
    for (a0, b0), (a1, b1) in zip(clips, clips[1:]):
        assert b0 <= a1 + 1e-6
    for s in segs:
        if s["keep"]:
            assert s["clips"][0][0] <= s["start"] and s["clips"][-1][1] >= s["end"]


def test_src_to_out_snaps_across_removed_pause():
    items = {"s": [{"a": 0.0, "d": 1.0, "out": 10.0}, {"a": 2.0, "d": 1.0, "out": 11.0}]}
    assert render.src_to_out(items, "s", 0.5, "start") == 10.5
    assert render.src_to_out(items, "s", 1.5, "start") == 11.0
    assert render.src_to_out(items, "s", 1.5, "end") == 11.0
    assert render.src_to_out(items, "s", 2.5, "start") == 11.5


def test_presenter_crop_follows_face_and_stays_in_frame():
    x, y, cw, ch, fo = render.presenter_crop(1920, 1080, [0.8, 0.3, 0.1, 0.18], 1080, 1920, 1.0)
    assert 0 <= x and x + cw <= 1920 and 0 <= y and y + ch <= 1080
    assert fo[0] > 0 and fo[2] < 1080      # face fully inside the output


def test_multiword_highlight():
    seg = {"words": [{"w": w, "s": i * 0.3, "e": i * 0.3 + 0.3} for i, w in enumerate(["กลับ", "ไม่", "พบ", "ใคร", "เลย"])],
           "highlight": ["ไม่พบใคร"]}
    subs = planner.make_subs(seg, planner.DEFAULT_SETTINGS)
    assert [p["w"] for s in subs for p in s["parts"] if p["hl"]] == ["ไม่", "พบ", "ใคร"]


def test_text_fit_shrinks_long_titles():
    long = "ข้อความยาวมากที่ต้องถูกย่อขนาดลงเพื่อไม่ให้ล้นจอวิดีโอแนวตั้ง"
    assert G.text_width(long, "Kanit ExtraBold", G.fit_size(long, "Kanit ExtraBold", 92, 900)) <= 900 or \
        G.fit_size(long, "Kanit ExtraBold", 92, 900) == 34


def test_panel_effect_keeps_split_layout_after_edit():
    """Regression: adding a panel effect (e.g. Paper Cut) to a sentence without basic b-roll must not be
    reverted to full-frame when the plan is saved (the effect would silently disappear)."""
    seg = {"id": "s1", "start": 0, "end": 1, "text": "ทดสอบ", "keep": True, "words": [{"w": "ทดสอบ", "s": 0, "e": 1}],
           "layout": "full", "zoom": "none", "sfx": "none", "broll": {"kind": "none"}, "faces": [], "highlight": []}
    old = {"settings": dict(planner.DEFAULT_SETTINGS), "source": {"duration": 1}, "segments": [dict(seg)]}
    new = {"settings": dict(planner.DEFAULT_SETTINGS),
           "segments": [dict(seg, layout="pip", effects=[{"id": "paper_cut", "params": {}}])]}
    out = planner.apply_edits(old, new)
    assert out["segments"][0]["layout"] == "pip"


def test_density_changes_effect_count():
    from engine import vision
    from engine.effects import selector
    import copy
    segs = A.classify_cuts(T.segments_from_subtitles(SAMPLES / "business_sample.srt"), {}, log=lambda *_: None)
    info = {"width": 1920, "height": 1080, "duration": 46.0, "fps": 30, "_silences": []}
    counts = {}
    for level in (1, 3):
        plan = planner.build_plan(dict(info), copy.deepcopy(segs), None, {}, [], {}, log=lambda *_: None)
        selector.direct(plan, {"mode": "auto", "density": level}, caps={"segmentation": False}, log=lambda *_: None)
        counts[level] = sum(len(s["effects"]) for s in plan["segments"] if s["keep"])
    assert counts[3] > counts[1]
