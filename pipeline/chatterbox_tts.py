"""Self-hosted Arabic TTS provider (Chatterbox) — a `TTSProvider` (voice.py).

Chatterbox (MIT, multilingual incl. Arabic, zero-shot voice cloning) is an open
alternative to ElevenLabs that runs on the local GPU, turning TTS from the
pipeline's only variable cost into a fixed cost. Open TTS returns no
ElevenLabs-style timestamps, so word timing is recovered by WhisperX forced
alignment against the exact spoken text — and this provider returns that timing
in the SAME character-level shape ElevenLabs does, so voice.py's
`_words_from_alignment`, `timing.json`, captions and `verify_timing` are all
unchanged (CLAUDE.md module contract).

The heavy torch/CUDA stack (Chatterbox + WhisperX) lives in a SEPARATE venv so
the pipeline venv stays torch-free and green. This class drives that venv's
`scripts/tts_worker.py` as a persistent subprocess over newline-delimited JSON
(stdin/stdout) — Arabic text crosses the boundary as UTF-8 bytes on a pipe,
never through a shell/argv codepage (CLAUDE.md hard rule 4). The worker loads
the models once and stays warm for the whole voice stage.
"""

from __future__ import annotations

import atexit
import base64
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pipeline import contract
from pipeline.contract import ContractError, ffmpeg_path
from pipeline.errors import StageError

STAGE = "voice"
WORKER = contract.ROOT / "scripts" / "tts_worker.py"
DEFAULT_AI_PYTHON = Path(r"D:\vd-ai\venv\Scripts\python.exe")


class ChatterboxTTS:
    """Persistent-worker Chatterbox provider. One request per scene; the worker
    process is started lazily on first use and reused (models stay loaded)."""

    def __init__(self, *, ai_python: str, model: str, language: str,
                 voice_ref: str, exaggeration: float, cfg_weight: float,
                 seed: int, hf_home: str) -> None:
        self.ai_python = Path(ai_python)
        self.model = model
        self.language = language
        self.voice_ref = voice_ref  # path to a ~5s reference wav, or "" for default
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.seed = seed
        self.hf_home = hf_home
        self._proc: subprocess.Popen | None = None
        self._logf = None  # worker stderr sink (a file, never a pipe — see below)
        self._log_path = Path(ai_python).parents[2] / "worker.log" \
            if len(Path(ai_python).parents) >= 3 else Path("worker.log")

    # -- provider Protocol ------------------------------------------------
    def signature(self) -> str:
        # Everything that changes the audio (so the voice_cache key invalidates
        # on any of these). A voice-ref file is identified by its bytes' hash so
        # swapping the reference clip re-synthesizes.
        ref_id = ""
        if self.voice_ref:
            p = Path(self.voice_ref)
            ref_id = f"{p.name}:{p.stat().st_size}" if p.exists() else self.voice_ref
        return json.dumps({
            "provider": "chatterbox", "model": self.model,
            "language": self.language, "voice_ref": ref_id,
            "exaggeration": self.exaggeration, "cfg_weight": self.cfg_weight,
            "seed": self.seed,
        }, sort_keys=True)

    def synthesize(
        self, text: str, prev_text: str, next_text: str, *,
        style: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        # Chatterbox has no prosody-continuity input, so prev/next are unused
        # for synthesis (they still key the cache upstream — conservative).
        # `style` carries per-scene delivery (exaggeration/cfg_weight from the
        # scene's mood); it overrides the provider defaults for this call only.
        style = style or {}
        exaggeration = float(style.get("exaggeration", self.exaggeration))
        cfg_weight = float(style.get("cfg_weight", self.cfg_weight))
        resp = self._request({
            "text": text,
            "language": self.language,
            "voice_ref": self.voice_ref,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
            "seed": self.seed,
        })
        if not resp.get("ok"):
            raise StageError(STAGE, f"Chatterbox worker: {resp.get('error', 'unknown error')}")
        try:
            wav = base64.b64decode(resp["wav_b64"])
            alignment = resp["alignment"]
            for key in ("characters", "character_start_times_seconds",
                        "character_end_times_seconds"):
                if not isinstance(alignment[key], list):
                    raise KeyError(key)
        except (KeyError, TypeError, ValueError) as exc:
            raise StageError(STAGE, f"malformed worker response: {exc!r}")
        return _wav_to_mp3(wav), alignment

    # -- worker process ---------------------------------------------------
    def _ensure_worker(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not self.ai_python.exists():
            raise StageError(
                STAGE,
                f"AI python not found at {self.ai_python} — set "
                f"voice.chatterbox.ai_python in config, or build the AI venv "
                f"(see docs/ai-video/SELF_HOSTED_TTS.md)",
            )
        env = {
            **_os_environ(),
            "HF_HOME": self.hf_home,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            # Quiet the model libraries so the worker's stderr stays small.
            "TQDM_DISABLE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
        }
        # CRITICAL: the worker prints tqdm/model logs to stderr; if that were a
        # PIPE we don't drain, the OS buffer fills (~64KB) and the worker blocks
        # forever mid-generation. Send stderr to a log file instead — no draining
        # needed, and it's there to read on failure.
        self._logf = open(self._log_path, "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen(
            [str(self.ai_python), str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._logf,
            text=True, encoding="utf-8", env=env, cwd=str(contract.ROOT),
        )
        atexit.register(self.close)
        return self._proc

    def _request(self, payload: dict) -> dict:
        proc = self._ensure_worker()
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise StageError(STAGE, f"Chatterbox worker pipe failed: {exc}") from exc
        if not line:
            err = self._read_log_tail()
            self.close()
            raise StageError(
                STAGE,
                f"Chatterbox worker exited early (see {self._log_path}):\n{err}",
            )
        try:
            return json.loads(line)
        except ValueError as exc:
            raise StageError(STAGE, f"non-JSON from worker: {line[:300]!r}") from exc

    def _read_log_tail(self, n: int = 1800) -> str:
        try:
            if self._logf is not None:
                self._logf.flush()
            return self._log_path.read_text(encoding="utf-8", errors="replace")[-n:]
        except OSError:
            return "(worker log unavailable)"

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self._logf is not None:
            try:
                self._logf.close()
            except OSError:
                pass
            self._logf = None


# -- helpers --------------------------------------------------------------
def _os_environ() -> dict:
    import os
    return dict(os.environ)


def _wav_to_mp3(wav: bytes) -> bytes:
    """Transcode the worker's WAV to MP3 (the format the voice stage stores and
    concatenates) using the pipeline's ffmpeg — keeps ffmpeg in this venv."""
    with tempfile.TemporaryDirectory(prefix="cbx-") as tmp:
        wav_path = Path(tmp) / "in.wav"
        mp3_path = Path(tmp) / "out.mp3"
        wav_path.write_bytes(wav)
        cmd = [
            ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(wav_path), "-codec:a", "libmp3lame",
            "-ar", "48000", "-b:a", "192k", str(mp3_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise StageError(STAGE, f"wav->mp3 failed: {proc.stderr.strip()[:300]}")
        return mp3_path.read_bytes()


def build(voice_cfg: dict, env: dict) -> "ChatterboxTTS":
    """Construct from the config `voice` section. No ElevenLabs key/voice_id
    needed. `voice.chatterbox` holds the knobs; sensible defaults otherwise."""
    ccfg = voice_cfg.get("chatterbox") or {}
    ai_python = str(ccfg.get("ai_python") or env.get("VD_AI_PYTHON") or DEFAULT_AI_PYTHON)
    return ChatterboxTTS(
        ai_python=ai_python,
        model=str(ccfg.get("model", "multilingual")),
        language=str(ccfg.get("language", "ar")),
        voice_ref=str(ccfg.get("voice_ref", "") or ""),
        exaggeration=float(ccfg.get("exaggeration", 0.5)),
        cfg_weight=float(ccfg.get("cfg_weight", 0.5)),
        seed=int(ccfg.get("seed", 0)),
        hf_home=str(ccfg.get("hf_home") or env.get("HF_HOME") or r"D:\vd-ai\models"),
    )
