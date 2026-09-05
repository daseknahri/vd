"""make_music_bed.build_command: structure only (no ffmpeg run, no network)."""

from pathlib import Path

from tools import make_music_bed as mmb


def test_build_command_layers_all_chord_voices():
    cmd = mmb.build_command("ffmpeg", Path("out.mp3"), 30.0)
    # one lavfi sine input per chord voice
    assert cmd.count("lavfi") == len(mmb._VOICES)
    assert sum(1 for a in cmd if a.startswith("sine=frequency=")) == len(mmb._VOICES)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert f"amix=inputs={len(mmb._VOICES)}:normalize=0" in graph
    # softening chain present
    for f in ("tremolo=", "chorus=", "lowpass=", "aecho=", "loudnorm="):
        assert f in graph
    # bounded output, stereo target, correct file
    assert cmd[-1] == "out.mp3"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "30.00"


def test_build_command_respects_duration_and_ffmpeg_path():
    cmd = mmb.build_command("C:/ff/ffmpeg.exe", Path("bed.mp3"), 12.5)
    assert cmd[0] == "C:/ff/ffmpeg.exe"
    assert cmd[cmd.index("-t") + 1] == "12.50"
    assert all("duration=12.50" in a for a in cmd if a.startswith("sine="))
