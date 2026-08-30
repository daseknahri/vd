"""Dub step 3: script.json -> voiceover.mp3 + timing.json (ElevenLabs).

Unlike pipeline/voice.py (scenes back-to-back), the dub places each Arabic clip
at its SOURCE-VIDEO timestamp so narration stays aligned with the picture, and
time-fits each clip into the gap before the next scene (pipeline.dub.place_scenes:
natural speed when it fits, atempo up to a cap, push only past the cap). The
whole track is assembled in one ffmpeg pass (per-scene atempo -> adelay to its
absolute start -> amix) onto the absolute [0, total] timeline captions.py and
dub_render expect. Reuses the ElevenLabs client + content-addressed voice_cache/
so re-runs never re-bill unchanged scenes.

  .venv\\Scripts\\python.exe scripts\\dub_voice.py <slug> [--force]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub  # noqa: E402
from pipeline.contract import ffmpeg_path  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="dub step 3: ElevenLabs voiceover")
    ap.add_argument("slug")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    cfg = contract.load_config(pdir)
    env = contract.load_env()

    if (project.has(contract.VOICEOVER) and project.has(contract.TIMING)
            and not args.force):
        print("voiceover.mp3 + timing.json already present (use --force)")
        return 0

    # Enforced translation gate: never spend without an approval marker.
    if not project.has(dub.TRANSLATION_APPROVED):
        print(f"translation not approved — review dub_review.html, then create "
              f"the marker:\n  run.py dub-approve {args.slug}\n"
              f"(or: touch projects/{args.slug}/{dub.TRANSLATION_APPROVED})")
        return 1

    try:
        script = project.script()
        segs = dub.load_segments(project)
        provider = dub.build_provider(cfg, env)   # raises if key/voice_id unset
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1

    story_start = float(segs["story_start"])
    story_len = float(segs["story_end"]) - story_start
    seg_by_id = {s["id"]: s for s in segs["segments"]}
    sig = provider.signature()
    cache_dir = pdir / "voice_cache"; cache_dir.mkdir(exist_ok=True)
    tmp = pdir / "voice_tmp"; tmp.mkdir(exist_ok=True)
    try:
        return _synth(project, script, seg_by_id, story_start, story_len,
                      provider, sig, cache_dir, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _synth(project, script, seg_by_id, story_start, story_len,
           provider, sig, cache_dir, tmp) -> int:
    scenes = script["scenes"]
    spoken = [s["narration_ar"].strip() for s in scenes]

    raw_durations, words0_all, billed = [], [], 0
    for i, sc in enumerate(scenes):
        prev_text = spoken[i - 1] if i > 0 else ""
        next_text = spoken[i + 1] if i < len(scenes) - 1 else ""
        audio, alignment, from_cache = dub.synthesize_cached(
            provider, cache_dir, sig, spoken[i], prev_text, next_text)
        if not from_cache:
            billed += len(spoken[i])
        rpath = tmp / f"raw_{sc['id']:03d}.mp3"
        rpath.write_bytes(audio)
        raw_durations.append(dub.probe_duration(rpath))
        try:
            words0_all.append(dub.words_from_alignment(spoken[i], alignment, 0.0))
        except Exception as exc:
            words0_all.append([])
            print(f"  scene {sc['id']}: word alignment unusable ({exc}); "
                  f"captions will use proportional timing")

    rel_starts = [float(seg_by_id[sc["id"]]["start"]) - story_start
                  for sc in scenes]
    plan = dub.place_scenes(raw_durations, rel_starts, story_len)

    timing_scenes = []
    for i, sc in enumerate(scenes):
        p = plan["placements"][i]
        words = [{"word": w["word"],
                  "start": round(p["start"] + w["start"] / p["speed"], 3),
                  "end": round(p["start"] + w["end"] / p["speed"], 3)}
                 for w in words0_all[i]]
        timing_scenes.append({"id": sc["id"], "start": p["start"],
                              "end": p["end"], "words": words})

    total = plan["total"]
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin"]
    for i in range(len(scenes)):
        cmd += ["-i", str(tmp / f"raw_{scenes[i]['id']:03d}.mp3")]
    parts, labels = [], []
    for i, p in enumerate(plan["placements"]):
        chain = f"[{i}:a]aresample=48000"
        if abs(p["speed"] - 1.0) > 1e-3:
            chain += f",atempo={p['speed']:.5f}"
        chain += f",adelay={p['delay_ms']}:all=1[a{i}]"
        parts.append(chain); labels.append(f"[a{i}]")
    parts.append("".join(labels)
                 + f"amix=inputs={len(labels)}:normalize=0:duration=longest[mix]")
    parts.append(f"[mix]apad,atrim=0:{total},aresample=48000[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]",
            "-c:a", "libmp3lame", "-ar", "48000", "-b:a", "192k",
            str(project.path(contract.VOICEOVER))]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        print(f"ERROR: ffmpeg assemble failed:\n{tail}")
        return 1

    timing = {"total_seconds": total, "scenes": timing_scenes}
    contract.validate_timing(timing)
    project.write_json(contract.TIMING, timing)
    overrun_ids = [scenes[i]["id"] for i in plan["overruns"]]
    sped = sum(1 for p in plan["placements"] if p["speed"] > 1.001)
    max_speed = max((p["speed"] for p in plan["placements"]), default=1.0)
    project.write_json(dub.VOICE_REPORT, {
        "workflow": "dub", "total_characters": sum(len(s) for s in spoken),
        "billed_characters": billed, "story_seconds": round(story_len, 3),
        "audio_seconds": total, "scenes_sped_up": sped,
        "max_speed": round(max_speed, 3), "overrun_scene_ids": overrun_ids,
    })
    print(f"wrote voiceover.mp3 ({total:.1f}s) + timing.json ; "
          f"billed {billed} chars ; {sped} scenes sped up (max {max_speed:.2f}x)"
          + (f" ; overruns: {overrun_ids}" if overrun_ids else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
