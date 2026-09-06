"""SILMA TTS provider — reliable Arabic MSA (silma-ai/silma-tts, F5-diffusion).

Chatterbox's Arabic is weak and loops on diacritized text; SILMA is purpose-built
for Arabic, diacritizes internally (CATT), and stays stable (validated on the same
scenes Chatterbox rambled on). It runs in its OWN venv (D:\\silma-tts\\.venv, the
F5 stack) behind the same `TTSProvider` interface, driven by scripts/silma_worker.py
over newline-delimited JSON — so the pipeline venv stays free of the F5 deps.

SILMA emits audio only (no word timestamps), so this provider recovers word timing
with the pipeline venv's faster-whisper (the same approach as the align stage) and
returns a character-level alignment in the SAME shape ElevenLabs/Chatterbox return,
so voice.py is unchanged. Set voice.provider: "silma" (+ optional voice.silma.*).
"""

from __future__ import annotations

import atexit
import base64
import io
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from pipeline import contract, wordtiming
from pipeline.contract import ContractError, ffmpeg_path
from pipeline.errors import StageError

STAGE = "voice"
WORKER = contract.ROOT / "scripts" / "silma_worker.py"
DEFAULT_SILMA_PYTHON = Path(r"D:\silma-tts\.venv\Scripts\python.exe")
DEFAULT_REF_FILE = Path(
    r"D:\silma-tts\src\silma_tts\infer\ref_audio_samples\ar.ref.24k.wav")
DEFAULT_REF_TEXT = ("ويدقق النظر في القرآن الكريم وسائر الكتب السماوية ويتبع "
                    "مسالك الرسل العظام عليهم الصلاة والسلام.")


class SilmaTTS:
    def __init__(self, *, silma_python: str, ref_file: str, ref_text: str,
                 seed: int, hf_home: str, nfe_step: int, cfg_strength: float,
                 speed: float, force_tashkeel: bool,
                 transcribe_cfg: dict | None = None) -> None:
        self.silma_python = Path(silma_python)
        self.ref_file = str(ref_file)
        self.ref_text = ref_text
        self.seed = seed
        self.hf_home = hf_home
        self.nfe_step = nfe_step
        self.cfg_strength = cfg_strength
        self.speed = speed
        self.force_tashkeel = force_tashkeel
        self.transcribe_cfg = transcribe_cfg or {}
        self._proc: subprocess.Popen | None = None
        self._logf = None
        self._whisper_model = None
        self._log_path = (Path(silma_python).parents[2] / "silma_worker.log"
                          if len(Path(silma_python).parents) >= 3
                          else Path("silma_worker.log"))

    # -- provider Protocol ------------------------------------------------
    def signature(self) -> str:
        p = Path(self.ref_file)
        ref_id = f"{p.name}:{p.stat().st_size}" if p.exists() else self.ref_file
        return json.dumps({
            "provider": "silma", "ref": ref_id, "ref_text": self.ref_text,
            "seed": self.seed, "nfe_step": self.nfe_step,
            "cfg_strength": self.cfg_strength, "speed": self.speed,
            "force_tashkeel": self.force_tashkeel,
        }, sort_keys=True, ensure_ascii=False)

    def synthesize(self, text: str, prev_text: str, next_text: str, *,
                   style: dict[str, Any] | None = None
                   ) -> tuple[bytes, dict[str, Any]]:
        # SILMA has no prosody-continuity input; prev/next are unused for
        # synthesis (still key the cache upstream — conservative). `style` (the
        # Chatterbox emotion knobs) does not map onto SILMA and is ignored.
        resp = self._request({
            "text": text, "ref_file": self.ref_file, "ref_text": self.ref_text,
            "seed": self.seed, "nfe_step": self.nfe_step,
            "cfg_strength": self.cfg_strength, "speed": self.speed,
            "force_tashkeel": self.force_tashkeel, "hf_home": self.hf_home,
        })
        if not resp.get("ok"):
            raise StageError(STAGE, f"SILMA worker: {resp.get('error', 'unknown error')}")
        try:
            wav = base64.b64decode(resp["wav_b64"])
            sr = int(resp["sr"])
        except (KeyError, ValueError) as exc:
            raise StageError(STAGE, f"malformed SILMA response: {exc!r}")
        alignment = self._align(wav, sr, text)
        return _wav_to_mp3(wav), alignment

    # -- alignment (pipeline-venv faster-whisper + shared wordtiming) ------
    def _align(self, wav_bytes: bytes, sr: int, spoken_text: str) -> dict[str, Any]:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            duration = w.getnframes() / float(w.getframerate() or sr or 1)
        model = self._whisper()
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(wav_bytes)
            tmp.close()
            segments, _info = model.transcribe(
                tmp.name, word_timestamps=True, language="ar")
            ref_words: list[str] = []
            ref_times: list[tuple[float, float]] = []
            for seg in segments:
                for w in (seg.words or []):
                    ref_words.append(w.word)
                    ref_times.append((float(w.start), float(w.end)))
        except Exception as exc:  # noqa: BLE001
            raise StageError(STAGE, f"SILMA alignment (whisper) failed: {exc}") from exc
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass
        spoken = spoken_text.split()
        times = wordtiming.match_times(ref_words, ref_times, spoken)
        filled = wordtiming.fill_gaps(times, duration)
        return wordtiming.char_alignment(spoken, filled)

    def _whisper(self):
        if self._whisper_model is None:
            from faster_whisper import WhisperModel
            tcfg = self.transcribe_cfg
            self._whisper_model = WhisperModel(
                tcfg.get("model", "small"),
                device=tcfg.get("device", "cpu"),
                compute_type=tcfg.get("compute_type", "int8"))
        return self._whisper_model

    # -- worker process (same pattern as chatterbox_tts) ------------------
    def _ensure_worker(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not self.silma_python.exists():
            raise StageError(
                STAGE,
                f"SILMA python not found at {self.silma_python} — set "
                f"voice.silma.silma_python in config, or install SILMA "
                f"(see docs/ai-video).",
            )
        env = {
            **dict(os.environ),
            "HF_HOME": self.hf_home,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "TQDM_DISABLE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "TRANSFORMERS_VERBOSITY": "error",
        }
        # Worker stderr -> a log file (utf-8), never a pipe we don't drain.
        self._logf = open(self._log_path, "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen(
            [str(self.silma_python), str(WORKER)],
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
            raise StageError(STAGE, f"SILMA worker pipe failed: {exc}") from exc
        if not line:
            err = self._read_log_tail()
            self.close()
            raise StageError(
                STAGE,
                f"SILMA worker exited early (see {self._log_path}):\n{err}",
            )
        try:
            return json.loads(line)
        except ValueError as exc:
            raise StageError(STAGE, f"non-JSON from SILMA worker: {line[:300]!r}") from exc

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


def _wav_to_mp3(wav: bytes) -> bytes:
    """WAV -> MP3 (the format voice.py stores + concatenates), via the pipeline's
    ffmpeg (keeps ffmpeg in this venv, not the SILMA one)."""
    with tempfile.TemporaryDirectory(prefix="silma-") as tmp:
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


def _resolve_reference(scfg: dict) -> tuple[str, str]:
    """(ref_file, ref_text) for the clone. An empty ref_file uses SILMA's bundled
    reference. A relative ref_file resolves against the repo root. ref_text comes
    from config, else a sibling `<stem>.txt` next to the wav — a matching
    transcript is REQUIRED (an empty one makes SILMA auto-transcribe, which hits a
    broken torchcodec on Windows), and the clip must be < 8s or SILMA clips it and
    drops the transcript."""
    ref = str(scfg.get("ref_file") or "").strip()
    if not ref:
        return str(DEFAULT_REF_FILE), DEFAULT_REF_TEXT
    p = Path(ref)
    if not p.is_absolute():
        p = contract.ROOT / ref
    ref_text = str(scfg.get("ref_text") or "").strip()
    if not ref_text:
        sib = p.with_suffix(".txt")
        if sib.exists():
            ref_text = sib.read_text(encoding="utf-8").strip()
    if not ref_text:
        raise ContractError(
            f"voice.silma.ref_file is set ({ref}) but there is no ref_text — add "
            f"voice.silma.ref_text, or a sibling {p.stem}.txt with the transcript."
        )
    return str(p), ref_text


def build(voice_cfg: dict, env: dict, transcribe_cfg: dict | None = None) -> "SilmaTTS":
    """Construct from config `voice.silma`. Sensible defaults use the bundled
    reference voice; set voice.silma.ref_file (+ a transcript) to clone another
    narrator — see _resolve_reference."""
    scfg = (voice_cfg or {}).get("silma") or {}
    silma_python = str(scfg.get("silma_python") or env.get("VD_SILMA_PYTHON")
                       or DEFAULT_SILMA_PYTHON)
    ref_file, ref_text = _resolve_reference(scfg)
    return SilmaTTS(
        silma_python=silma_python,
        ref_file=ref_file,
        ref_text=ref_text,
        seed=int(scfg.get("seed", 0) or 0),
        hf_home=str(scfg.get("hf_home") or env.get("HF_HOME") or r"D:\vd-ai\models"),
        nfe_step=int(scfg.get("nfe_step", 16)),
        cfg_strength=float(scfg.get("cfg_strength", 2.0)),
        speed=float(scfg.get("speed", 1.0)),
        force_tashkeel=bool(scfg.get("force_tashkeel", False)),
        transcribe_cfg=transcribe_cfg,
    )
