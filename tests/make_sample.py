"""Build a synthetic end-to-end sample project and run captions+render+review.

No API keys needed: voiceover is a generated tone, clips are lavfi sources,
scene 3's clip is deliberately missing to exercise the placeholder+FLAGGED
path. Timing has leading silence (0.5s) and inter-scene gaps to exercise
the absolute-timeline cuts.

Run:  .venv\\Scripts\\python.exe tests\\make_sample.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import captions, render_ffmpeg, review
from pipeline.contract import (
    CLIPS_DIR, SCRIPT, TIMING, VOICEOVER, Project, ffmpeg_path,
    load_config, validate_script, validate_timing,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "projects" / "sample-demo"
FF = ffmpeg_path()

if SAMPLE.exists():
    shutil.rmtree(SAMPLE)
SAMPLE.mkdir(parents=True)
project = Project(dir=SAMPLE)

script = {
    "meta": {"source_url": "sample://demo", "audience": "general Arab",
             "dialect": "MSA", "target_seconds": 12},
    "hook": "هل تعرف كم يكلف صنع فيديو واحد؟",
    "scenes": [
        {"id": 1,
         "narration_ar": "هل تعرف كم يكلف صنع فيديو واحد بالكامل؟",
         "keywords": [["studio camera closeup"]],
         "mood": "energetic", "target_seconds": 4},
        {"id": 2,
         "narration_ar": "جربنا iPhone 15 في شوارع نيويورك الصاخبة",
         "keywords": [["city street night"]],
         "mood": "energetic", "target_seconds": 4},
        {"id": 3,
         "narration_ar": "والنتيجة كانت أفضل مما توقعنا بكثير",
         "keywords": [["sunrise over desert"]],
         "mood": "calm", "target_seconds": 4},
    ],
    "post": {"title": "تجربة صناعة الفيديو", "description": "عينة اختبار.",
             "hashtags": ["#تقنية"]},
}
validate_script(script)
project.write_json(SCRIPT, script)


def words_for(text: str, start: float, end: float) -> list[dict]:
    toks = text.split()
    step = (end - start) / len(toks)
    return [{"word": w, "start": round(start + i * step, 3),
             "end": round(start + (i + 1) * step, 3)}
            for i, w in enumerate(toks)]


timing = {
    "total_seconds": 12.0,
    "scenes": [
        {"id": 1, "start": 0.5, "end": 4.0, "words": words_for(script["scenes"][0]["narration_ar"], 0.5, 4.0)},
        {"id": 2, "start": 4.4, "end": 8.0, "words": words_for(script["scenes"][1]["narration_ar"], 4.4, 8.0)},
        {"id": 3, "start": 8.2, "end": 11.5, "words": words_for(script["scenes"][2]["narration_ar"], 8.2, 11.5)},
    ],
}
validate_timing(timing)
project.write_json(TIMING, timing)

# Voiceover: 12s tone (audible, content irrelevant).
subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=12",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(SAMPLE / VOICEOVER)], check=True)

# Clips for scenes 1-2 (distinct looks); scene 3 missing on purpose.
clips = SAMPLE / CLIPS_DIR
clips.mkdir()
subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=size=608x1080:rate=30:duration=5",
                "-pix_fmt", "yuv420p", str(clips / "scene_001.mp4")], check=True)
subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "gradients=size=608x1080:rate=30:duration=5",
                "-pix_fmt", "yuv420p", str(clips / "scene_002.mp4")], check=True)

cfg = load_config(SAMPLE)
env: dict = {}

captions.run(project, cfg, env)
print("captions done:", len(json.loads((SAMPLE / "captions" / "manifest.json").read_text(encoding="utf-8"))["frames"]), "frames")
render_ffmpeg.run(project, cfg, env)
print("render done")
review.run(project, cfg, env)
print("review done")

report = project.read_json("render_report.json")
print("gaps:", report.get("gaps"))
probe = report.get("output", report.get("probe", {}))
print("output probe:", json.dumps(probe)[:300])
print("final:", (SAMPLE / "final.mp4").stat().st_size, "bytes")
