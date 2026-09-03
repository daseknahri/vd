"""AI-venv worker: Chatterbox Multilingual TTS + WhisperX forced alignment.

Runs in the SEPARATE GPU venv (D:\\vd-ai\\venv — torch/CUDA), driven by
pipeline/chatterbox_tts.py over newline-delimited JSON on stdin/stdout. One
request line -> one response line. Keeps the models loaded across requests so
the whole voice stage pays the load cost once.

Per request it: (1) synthesizes Arabic audio with Chatterbox, (2) runs WhisperX
forced alignment of that audio against the KNOWN spoken text (so word count is
preserved and we never transcribe), (3) returns 24 kHz WAV (base64) + a
character-level alignment in the SAME shape ElevenLabs returns, so voice.py is
unchanged. Word->char expansion + matching live in pipeline/wordtiming.py
(shared with the align stage).

All library logging is forced to stderr; stdout carries ONLY protocol JSON.
"""

import base64
import io
import json
import sys
import wave
from pathlib import Path

# Protocol stream = the REAL stdout; everything else (model logs) -> stderr.
_OUT = sys.stdout
sys.stdout = sys.stderr

# Repo root on sys.path so the shared, stdlib-only timing helpers import here
# too (the repo uses implicit namespace packages — no heavy __init__).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import wordtiming  # noqa: E402

_TTS = None            # ChatterboxMultilingualTTS
_ALIGN = None          # (model, metadata)
_DEVICE = None
_ALIGN_DEVICE = None
_ALIGN_LANG = None


def _send(obj):
    _OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _OUT.flush()


# -- lazy model loading ---------------------------------------------------
def _ensure_loaded(language):
    global _TTS, _ALIGN, _DEVICE, _ALIGN_DEVICE, _ALIGN_LANG
    import torch
    if _DEVICE is None:
        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    if _TTS is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _TTS = ChatterboxMultilingualTTS.from_pretrained(device=_DEVICE)
    if _ALIGN is None or _ALIGN_LANG != language:
        import whisperx
        # Forced alignment only needs the wav2vec2 aligner (NOT the whisper ASR
        # model) — big VRAM saving on an 8 GB card. Try GPU, fall back to CPU.
        _ALIGN_DEVICE = _DEVICE
        try:
            model, meta = whisperx.load_align_model(language_code=language, device=_DEVICE)
        except Exception:  # noqa: BLE001 — e.g. CUDA OOM loading the aligner
            _ALIGN_DEVICE = "cpu"
            model, meta = whisperx.load_align_model(language_code=language, device="cpu")
        _ALIGN = (model, meta)
        _ALIGN_LANG = language


# -- synthesis + alignment ------------------------------------------------
def _wav_bytes(wave_1d, sr):
    """float32 mono [-1,1] -> 16-bit PCM WAV bytes (stdlib only)."""
    import numpy as np
    pcm = np.clip(wave_1d, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _forced_align(text, audio16k):
    """WhisperX forced alignment -> list[(start,end)] aligned to text.split()."""
    import whisperx
    model, meta = _ALIGN
    duration = len(audio16k) / 16000.0
    segments = [{"start": 0.0, "end": duration, "text": text}]
    result = whisperx.align(segments, model, meta, audio16k, _ALIGN_DEVICE,
                            return_char_alignments=False)
    ref_words, ref_times = [], []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            ref_words.append(w.get("word", ""))
            s, e = w.get("start"), w.get("end")
            ref_times.append((float(s), float(e))
                             if s is not None and e is not None else None)
    spoken = text.split()
    times = wordtiming.match_times(ref_words, ref_times, spoken)
    return wordtiming.fill_gaps(times, duration)


def _handle(req):
    import torch
    import torchaudio
    text = req["text"]
    language = req.get("language", "ar")
    _ensure_loaded(language)

    seed = int(req.get("seed") or 0)
    if seed:
        torch.manual_seed(seed)
    kw = dict(language_id=language,
              exaggeration=float(req.get("exaggeration", 0.5)),
              cfg_weight=float(req.get("cfg_weight", 0.5)))
    ref = req.get("voice_ref") or ""
    if ref:
        kw["audio_prompt_path"] = ref

    wav = _TTS.generate(text, **kw)          # torch tensor, shape [1, N] @ _TTS.sr
    sr = int(_TTS.sr)
    wav = wav.detach().to("cpu")
    if wav.dim() == 2:
        wav = wav[0]
    # 16 kHz mono for the aligner; original sr for the returned audio.
    audio16k = torchaudio.functional.resample(wav, sr, 16000).numpy().astype("float32")
    word_times = _forced_align(text, audio16k)
    alignment = wordtiming.char_alignment(text.split(), word_times)

    return {"ok": True,
            "wav_b64": base64.b64encode(_wav_bytes(wav.numpy().astype("float32"), sr)).decode(),
            "sr": sr,
            "alignment": alignment,
            "align_device": _ALIGN_DEVICE}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as exc:
            _send({"ok": False, "error": f"bad request json: {exc}"})
            continue
        try:
            _send(_handle(req))
        except Exception as exc:  # noqa: BLE001 — report, keep the worker alive
            import traceback
            _send({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]})


if __name__ == "__main__":
    main()
