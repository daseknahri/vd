# -*- coding: utf-8 -*-
"""Pure word-timing helpers shared by the align stage and the TTS worker.
No network, no models — plain functions."""

import pytest

from pipeline import voice, wordtiming


def test_normalize_strips_tashkeel_punct_and_casefolds():
    assert wordtiming.normalize("Hello,") == "hello"
    # diacritized == undiacritized after normalization
    assert wordtiming.normalize("مَرْحَبًا") == wordtiming.normalize("مرحبا")
    # pure punctuation normalizes to empty
    assert wordtiming.normalize("،") == ""


def test_match_times_aligns_identical_sequences():
    ref = ["one", "two", "three"]
    times = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    assert wordtiming.match_times(ref, times, ref) == times


def test_match_times_unmatched_word_is_none():
    out = wordtiming.match_times(["a"], [(0.0, 1.0)], ["a", "zzz"])
    assert out[0] == (0.0, 1.0)
    assert out[1] is None


def test_match_times_ignores_diacritics():
    out = wordtiming.match_times(["مرحبا"], [(0.0, 1.0)], ["مَرْحَبًا"])
    assert out[0] == (0.0, 1.0)


def test_fill_gaps_interpolates_between_matched():
    filled = wordtiming.fill_gaps([(0.0, 1.0), None, (2.0, 3.0)], total=3.0)
    assert filled[0] == (0.0, 1.0)
    assert filled[2] == (2.0, 3.0)
    assert 1.0 <= filled[1][0] <= filled[1][1] <= 2.0


def test_fill_gaps_all_none_distributes_evenly():
    assert wordtiming.fill_gaps([None, None], total=4.0) == [(0.0, 2.0), (2.0, 4.0)]


def test_char_alignment_shape_is_consistent():
    a = wordtiming.char_alignment(["ab", "cd"], [(0.0, 0.4), (0.5, 1.0)])
    n = len(a["characters"])
    assert n == len(a["character_start_times_seconds"]) == len(a["character_end_times_seconds"])
    assert " " in a["characters"]  # word separator present


def test_char_alignment_roundtrips_through_voice_words_from_alignment():
    """The whole point: an open-TTS char alignment must let voice.py recover the
    exact per-word [start, end] it would from ElevenLabs."""
    spoken = ["مرحبا", "بالعالم"]
    word_times = [(0.10, 0.52), (0.60, 1.30)]
    alignment = wordtiming.char_alignment(spoken, word_times)
    words = voice._words_from_alignment(" ".join(spoken), alignment, offset=0.0)
    assert [w["word"] for w in words] == spoken
    for w, (s, e) in zip(words, word_times):
        assert w["start"] == pytest.approx(s, abs=1e-3)
        assert w["end"] == pytest.approx(e, abs=1e-3)


def test_char_alignment_offset_is_applied():
    alignment = wordtiming.char_alignment(["a", "bb"], [(0.0, 0.5), (0.5, 1.0)])
    words = voice._words_from_alignment("a bb", alignment, offset=10.0)
    assert words[0]["start"] == pytest.approx(10.0, abs=1e-3)
    assert words[1]["end"] == pytest.approx(11.0, abs=1e-3)
