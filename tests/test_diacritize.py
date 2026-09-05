# -*- coding: utf-8 -*-
"""Diacritizer tests. CATT is mocked — no model download, no onnxruntime, no
network. Verifies the word-count safety net and graceful degradation."""

from pipeline import diacritize


class FakeCATT:
    def __init__(self, mapping):
        self.mapping = mapping

    def do_tashkeel_batch(self, texts, verbose=False):
        return [self.mapping.get(t, t) for t in texts]


def test_diacritize_batch_returns_diacritized(monkeypatch):
    monkeypatch.setattr(diacritize, "_load",
                        lambda: FakeCATT({"العلم نور": "الْعِلْمُ نُورٌ"}))
    assert diacritize.diacritize_batch(["العلم نور"]) == ["الْعِلْمُ نُورٌ"]


def test_diacritize_batch_wordcount_mismatch_falls_back(monkeypatch):
    # model returns a different token count -> None so the caller keeps plain text
    monkeypatch.setattr(diacritize, "_load",
                        lambda: FakeCATT({"احب": "أَحَبَّ هُ"}))
    assert diacritize.diacritize_batch(["احب"]) == [None]


def test_diacritize_batch_unavailable_is_all_none(monkeypatch):
    monkeypatch.setattr(diacritize, "_load", lambda: None)
    assert diacritize.diacritize_batch(["a", "b"]) == [None, None]


def test_diacritize_batch_empty():
    assert diacritize.diacritize_batch([]) == []


def test_diacritize_batch_survives_model_exception(monkeypatch):
    class Boom:
        def do_tashkeel_batch(self, *a, **k):
            raise RuntimeError("model blew up")
    monkeypatch.setattr(diacritize, "_load", lambda: Boom())
    assert diacritize.diacritize_batch(["a"]) == [None]  # never raises


def test_available_reflects_load(monkeypatch):
    monkeypatch.setattr(diacritize, "_load", lambda: object())
    assert diacritize.available() is True
    monkeypatch.setattr(diacritize, "_load", lambda: None)
    assert diacritize.available() is False
