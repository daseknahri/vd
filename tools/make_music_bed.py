"""Synthesize a simple, warm instrumental bed with ffmpeg — no download, no cost.

The faceless pipeline ducks a music bed under the narration (see
render_ffmpeg._audio_filter) but ships nothing in assets/music/ by default, so
videos are voice-only. This builds a gentle ambient pad (a soft Fmaj7 chord with
slow movement + space) to sit under the voice and carry the "entrance" swell.
It is deliberately unobtrusive — a real, rights-cleared track will always sound
richer; drop one into assets/music/ and it wins (first file alphabetically).

    python tools/make_music_bed.py                 # -> assets/music/soft_pad.mp3
    python tools/make_music_bed.py --seconds 60 --out assets/music/bed.mp3

Pure `build_command` (argv only) is unit-tested; main() runs ffmpeg.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import contract  # noqa: E402

# A warm Fmaj7 voicing (bass + chord tones). Maj7 gives the gentle,
# slightly-yearning colour that fits a tender storybook tone; each tone's gain is
# balanced so the sum never clips before the softening chain.
_VOICES = [
    (87.31, 0.30),   # F2  — sub bass
    (174.61, 0.20),  # F3
    (220.00, 0.16),  # A3
    (261.63, 0.15),  # C4
    (329.63, 0.10),  # E4  — the maj7 colour, kept quiet
]


def build_command(ffmpeg: str, out_path: Path, seconds: float) -> list[str]:
    """The ffmpeg argv that renders the pad. Layered sines -> slow tremolo
    (breathing) -> chorus (width/warmth) -> lowpass (soften) -> echo (space).
    No fades: the bed loops in render, so it must stay at a constant level for a
    seamless seam; render applies its own fade-in + ducking."""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for freq, _gain in _VOICES:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds:.2f}"]
    mixes = "".join(
        f"[{i}:a]volume={gain:.3f}[v{i}];" for i, (_f, gain) in enumerate(_VOICES)
    )
    chain = "".join(f"[v{i}]" for i in range(len(_VOICES)))
    graph = (
        mixes
        + f"{chain}amix=inputs={len(_VOICES)}:normalize=0[m];"
        + "[m]tremolo=f=0.12:d=0.4,"
          "chorus=0.6:0.9:50|60|70:0.4|0.3|0.35:0.25|0.4|0.3:2|2.3|1.7,"
          "lowpass=f=1800,"
          "aecho=0.8:0.7:80:0.4,"
          "volume=0.8,"
          "loudnorm=I=-19:TP=-2.0:LRA=11,"
          "aformat=channel_layouts=stereo,aresample=48000[out]"
    )
    cmd += [
        "-filter_complex", graph, "-map", "[out]",
        "-t", f"{seconds:.2f}", "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_path),
    ]
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize a soft music bed.")
    parser.add_argument("--seconds", type=float, default=45.0)
    parser.add_argument(
        "--out", type=Path,
        default=contract.ROOT / "assets" / "music" / "soft_pad.mp3")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(contract.ffmpeg_path("ffmpeg"), args.out, args.seconds)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(f"ffmpeg failed: {proc.stderr.strip()[:500]}\n")
        return 1
    print(f"wrote {args.out} ({args.seconds:.0f}s soft pad)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
