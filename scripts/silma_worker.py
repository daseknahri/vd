"""SILMA-venv worker: SILMA TTS generation (audio only).

Runs in the SEPARATE SILMA venv (D:\\silma-tts\\.venv — torch/CUDA + the F5
stack), driven by pipeline/silma_tts.py over newline-delimited JSON on
stdin/stdout. One request line -> one WAV (base64) line. The model loads once and
stays resident, so the voice stage pays the load cost once.

Word timing is NOT done here (SILMA is a diffusion model with no word timestamps);
the provider aligns the returned audio with the pipeline venv's faster-whisper, so
this worker stays minimal and needs no extra deps.

All library logging (incl. SILMA's own prints + CATT's first-run emoji banner) is
forced to stderr; stdout carries ONLY protocol JSON.
"""

import base64
import io
import json
import sys
import wave

# Protocol stream = the REAL stdout; everything else (model logs) -> stderr.
_OUT = sys.stdout
sys.stdout = sys.stderr

_TTS = None  # SilmaTTS, loaded once


def _send(obj):
    _OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _OUT.flush()


def _ensure(req):
    global _TTS
    if _TTS is None:
        from silma_tts.api import SilmaTTS
        # enable_normalizer=False skips nemo/pynini (unavailable on Windows);
        # force_tashkeel handled per request in infer().
        _TTS = SilmaTTS(enable_normalizer=False, force_tashkeel=True,
                        hf_cache_dir=req.get("hf_home") or None)
    return _TTS


def _wav_bytes(wave_1d, sr):
    """float32 mono [-1,1] -> 16-bit PCM WAV bytes (stdlib only)."""
    import numpy as np
    pcm = (np.clip(wave_1d, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _handle(req):
    import numpy as np
    tts = _ensure(req)
    seed = req.get("seed")
    seed = int(seed) if seed not in (None, 0, "") else None
    wav, sr, _spec = tts.infer(
        ref_file=req["ref_file"],
        ref_text=req["ref_text"],
        gen_text=req["text"],
        normalize_numbers=False,
        force_tashkeel=bool(req.get("force_tashkeel", True)),
        seed=seed,
        nfe_step=int(req.get("nfe_step", 16)),
        cfg_strength=float(req.get("cfg_strength", 2.0)),
        speed=float(req.get("speed", 1.0)),
        show_info=lambda *a, **k: None,
    )
    wav = np.asarray(wav, dtype="float32")
    return {"ok": True,
            "wav_b64": base64.b64encode(_wav_bytes(wav, sr)).decode(),
            "sr": int(sr)}


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
