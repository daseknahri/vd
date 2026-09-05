"""make_music_bed.build_pad: pure numpy synthesis (no ffmpeg, no network)."""

import wave

import numpy as np

from tools import make_music_bed as mmb


def test_build_pad_shape_and_range():
    pad = mmb.build_pad(4.0)
    assert pad.shape == (int(4.0 * mmb.SR), 2)
    assert pad.dtype == np.float32
    assert np.max(np.abs(pad)) <= 0.71          # peak-normalized to ~0.7
    assert float(np.std(pad)) > 0.01            # not silent / not a DC tone


def test_build_pad_is_deterministic():
    assert np.array_equal(mmb.build_pad(3.0), mmb.build_pad(3.0))


def test_build_pad_has_stereo_width():
    pad = mmb.build_pad(4.0)
    # the Haas-delayed right channel differs from the left (real stereo image)
    assert not np.array_equal(pad[:, 0], pad[:, 1])


def test_write_wav_roundtrips(tmp_path):
    out = tmp_path / "bed.wav"
    mmb.write_wav(out, mmb.build_pad(1.0))
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == mmb.SR
        assert w.getnframes() == int(1.0 * mmb.SR)
