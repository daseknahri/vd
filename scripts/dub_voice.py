"""Dub step 3: script.json -> voiceover.mp3 + timing.json (ElevenLabs).

Unlike pipeline/voice.py (which lays scenes back-to-back), the dub places each
Arabic clip at its SOURCE-VIDEO timestamp so the narration stays aligned with
the picture. Each clip is time-fitted into the gap before the next scene:
played at natural speed when it fits, gently sped up (atempo, capped at
MAX_SPEED) when it would overrun, and only allowed to push later scenes when
even the cap is not enough. The whole voiceover is assembled in one ffmpeg
pass (per-scene atempo -> adelay to its absolute start -> amix), so scenes
never overlap and the track lands on the absolute [0, total] timeline that
captions.py and the render step expect.

Reuses the ElevenLabs client + content-addressed cache from pipeline.voice,
so re-runs never re-bill unchanged scenes.

  .venv\\Scripts\\python.exe scripts\\dub_voice.py romeo-juliet-dub
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, voice  # noqa: E402
from pipeline.contract import ffmpeg_path  # noqa: E402

MAX_SPEED = 1.30   # never speed a clip up by more than 30%
MIN_GAP = 0.05     # seconds; below this a "slot" is treated as unusable


def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else "romeo-juliet-dub"
    force = "--force" in sys.argv[2:]
    pdir = ROOT / "projects" / slug
    project = contract.Project(pdir)
    cfg = contract.load_config(pdir)
    env = contract.load_env()

    if (project.has(contract.VOICEOVER) and project.has(contract.TIMING)
            and not force):
        print("voiceover.mp3 + timing.json already present (use --force)")
        return 0

    script = project.script()
    segs = json.loads((pdir / "dub_segments.json").read_text(encoding="utf-8"))
    story_start = float(segs["story_start"])
    story_len = float(segs["story_end"]) - story_start
    seg_by_id = {s["id"]: s for s in segs["segments"]}

    provider = voice._build_provider(cfg, env)   # raises if key/voice_id unset
    sig = provider.signature()
    cache_dir = pdir / "voice_cache"; cache_dir.mkdir(exist_ok=True)
    tmp = pdir / "voice_tmp"; tmp.mkdir(exist_ok=True)

    scenes = script["scenes"]
    spoken = [s["narration_ar"].strip() for s in scenes]

    # 1. Synthesize every scene (cache-backed) and measure raw durations.
    raw: list[dict] = []
    billed = 0
    for i, sc in enumerate(scenes):
        prev_text = spoken[i - 1] if i > 0 else ""
        next_text = spoken[i + 1] if i < len(scenes) - 1 else ""
        audio, alignment, from_cache = voice._synthesize_cached(
            provider, cache_dir, sig, spoken[i], prev_text, next_text)
        if not from_cache:
            billed += len(spoken[i])
        rpath = tmp / f"raw_{sc['id']:03d}.mp3"
        rpath.write_bytes(audio)
        dur = voice._probe_duration(rpath)
        try:
            words0 = voice._words_from_alignment(spoken[i], alignment, 0.0)
        except Exception as exc:   # alignment/word-count mismatch -> caption
            words0 = []            # stage falls back to proportional timing
            print(f"  scene {sc['id']}: word alignment unusable ({exc}); "
                  f"captions will use proportional timing")
        raw.append({"sc": sc, "path": rpath, "dur": dur, "words0": words0})

    # 2. Place each clip at its source timestamp, fitting into the gap ahead.
    timing_scenes: list[dict] = []
    delays_ms: list[int] = []
    speeds: list[float] = []
    prev_end = 0.0
    overruns: list[int] = []
    for i, r in enumerate(raw):
        sid = r["sc"]["id"]
        desired = float(seg_by_id[sid]["start"]) - story_start
        start = max(desired, prev_end)
        nxt = (float(seg_by_id[raw[i + 1]["sc"]["id"]]["start"]) - story_start
               if i < len(raw) - 1 else story_len)
        available = nxt - start
        speed = 1.0
        if available > MIN_GAP and r["dur"] > available:
            speed = min(MAX_SPEED, r["dur"] / available)
            if r["dur"] / speed > available + 1e-3:
                overruns.append(sid)
        fitted = r["dur"] / speed
        end = start + fitted
        words = [{"word": w["word"],
                  "start": round(start + w["start"] / speed, 3),
                  "end": round(start + w["end"] / speed, 3)}
                 for w in r["words0"]]
        timing_scenes.append({"id": sid, "start": round(start, 3),
                              "end": round(end, 3), "words": words})
        delays_ms.append(int(round(start * 1000)))
        speeds.append(speed)
        prev_end = end

    total = round(max(prev_end, story_len), 3)

    # 3. One ffmpeg pass: atempo per scene -> delay to absolute start -> sum.
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin"]
    for r in raw:
        cmd += ["-i", str(r["path"])]
    parts = []
    labels = []
    for i, (d_ms, sp) in enumerate(zip(delays_ms, speeds)):
        chain = f"[{i}:a]aresample=48000"
        if abs(sp - 1.0) > 1e-3:
            chain += f",atempo={sp:.5f}"
        chain += f",adelay={d_ms}:all=1[a{i}]"
        parts.append(chain)
        labels.append(f"[a{i}]")
    parts.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:normalize=0:duration=longest[mix]"
    )
    parts.append(f"[mix]apad,atrim=0:{total},aresample=48000[out]")
    voice_path = project.path(contract.VOICEOVER)
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]",
            "-c:a", "libmp3lame", "-ar", "48000", "-b:a", "192k",
            str(voice_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        print(f"ERROR: ffmpeg assemble failed:\n{tail}")
        return 1

    timing = {"total_seconds": total, "scenes": timing_scenes}
    contract.validate_timing(timing)
    project.write_json(contract.TIMING, timing)
    project.write_json("voice_report.json", {
        "workflow": "dub",
        "total_characters": sum(len(s) for s in spoken),
        "billed_characters": billed,
        "story_seconds": round(story_len, 3),
        "audio_seconds": total,
        "scenes_sped_up": sum(1 for s in speeds if s > 1.001),
        "max_speed": round(max(speeds), 3),
        "overrun_scene_ids": overruns,
    })
    print(f"wrote voiceover.mp3 ({total:.1f}s) + timing.json ; "
          f"billed {billed} chars ; "
          f"{sum(1 for s in speeds if s > 1.001)} scenes sped up "
          f"(max {max(speeds):.2f}x)"
          + (f" ; overruns: {overruns}" if overruns else ""))
    # keep voice_tmp raw mp3s? remove to stay tidy (cache holds the billable audio)
    for p in tmp.glob("raw_*.mp3"):
        p.unlink()
    try:
        tmp.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
