"""Synthesize a warm instrumental bed with numpy — no download, no cost.

The faceless pipeline ducks a music bed under the narration (render_ffmpeg
_audio_filter) but ships nothing in assets/music/ by default, so videos are
voice-only. A single held chord sounds like a test tone; this synthesizes a
gentle four-chord pad PROGRESSION (I-V-vi-IV — the warm, hopeful, storybook
cadence) with slow swells, soft harmonics and a little stereo chorus, so there's
real musical movement under the voice. Deliberately understated — a real,
rights-cleared track (drop it in assets/music/, it wins alphabetically) will
always sound richer.

    python tools/make_music_bed.py                 # -> assets/music/soft_pad.mp3
    python tools/make_music_bed.py --seconds 60 --out assets/music/bed.mp3

Pure `build_pad` (numpy only) is unit-tested; main() writes a WAV then encodes
to MP3 with the pipeline's ffmpeg.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import contract  # noqa: E402

SR = 48000
# I-V-vi-IV in C major, voiced in a warm mid register (root, third, fifth Hz).
_CHORDS = [
    [130.81, 164.81, 196.00],  # C  major  (C3 E3 G3)
    [196.00, 246.94, 293.66],  # G  major  (G3 B3 D4)
    [220.00, 261.63, 329.63],  # Am (A3 C4 E4)
    [174.61, 220.00, 261.63],  # F  major  (F3 A3 C4)
]
_SEC_PER_CHORD = 4.0
_CROSSFADE = 1.6


def _chord(freqs: list[float], dur: float) -> np.ndarray:
    """One chord: each note as a few soft harmonics + a slightly detuned twin
    (chorus warmth) + a sub-octave root, under a raised-cosine swell envelope."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n, dtype=np.float64)
    for f in freqs:
        for harm, amp in ((1, 1.0), (2, 0.26), (3, 0.10)):
            sig += amp * np.sin(2 * np.pi * f * harm * t)
        sig += 0.5 * np.sin(2 * np.pi * f * 1.003 * t)  # detuned twin
    sig += 1.1 * np.sin(2 * np.pi * (freqs[0] / 2) * t)  # sub-bass root
    env = np.hanning(n)  # smooth attack + release => pad swell + crossfade
    return sig * env


def build_pad(seconds: float) -> np.ndarray:
    """Stereo float32 pad, shape (seconds*SR, 2), peak-normalized to ~0.7."""
    total = int(seconds * SR)
    stride = int((_SEC_PER_CHORD - _CROSSFADE) * SR)
    buf = np.zeros(total + int(_SEC_PER_CHORD * SR), dtype=np.float64)
    i = 0
    start = 0
    while start < total:
        w = _chord(_CHORDS[i % len(_CHORDS)], _SEC_PER_CHORD)
        buf[start:start + len(w)] += w
        start += stride
        i += 1
    mono = buf[:total]
    # slow "breathing" amplitude LFO
    t = np.arange(total) / SR
    mono *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.06 * t)
    peak = float(np.max(np.abs(mono))) or 1.0
    mono = mono / peak * 0.7
    # gentle stereo width: a few-ms Haas delay on the right channel
    delay = int(0.008 * SR)
    right = np.concatenate([np.zeros(delay), mono])[:total]
    return np.stack([mono, right], axis=1).astype(np.float32)


def write_wav(path: Path, stereo: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize a soft music bed.")
    parser.add_argument("--seconds", type=float, default=48.0)
    parser.add_argument(
        "--out", type=Path,
        default=contract.ROOT / "assets" / "music" / "soft_pad.mp3")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    pad = build_pad(args.seconds)
    with tempfile.TemporaryDirectory(prefix="bed-") as tmp:
        wav_path = Path(tmp) / "pad.wav"
        write_wav(wav_path, pad)
        cmd = [
            contract.ffmpeg_path("ffmpeg"), "-y", "-hide_banner",
            "-loglevel", "error", "-i", str(wav_path),
            "-c:a", "libmp3lame", "-b:a", "192k", str(args.out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(f"ffmpeg failed: {proc.stderr.strip()[:500]}\n")
        return 1
    print(f"wrote {args.out} ({args.seconds:.0f}s chord-progression pad)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
