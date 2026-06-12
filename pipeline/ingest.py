"""Ingest stage: source URL -> research transcript.

Downloads the source's AUDIO ONLY via the yt-dlp Python API (research input
— nothing from it ever enters the output), transcribes it locally with
faster-whisper, and writes transcript.txt plus ingest_report.json
(title/duration/uploader when the extractor provides them).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline import contract
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

STAGE = "ingest"
INGEST_REPORT = "ingest_report.json"  # <stage>_report.json convention
AUDIO_STEM = "source_audio"           # source_audio.<ext>, ext chosen by yt-dlp
# Silence between two segments (seconds) that starts a new paragraph.
_PARAGRAPH_GAP_S = 1.5


def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None:
    """source_url.txt -> transcript.txt (+ ingest_report.json)."""
    if project.has(contract.TRANSCRIPT) and not force:
        return
    if not project.has(contract.SOURCE_URL):
        raise ContractError(
            f"{contract.SOURCE_URL} not found in {project.dir} — "
            "ingest needs a source URL to work from"
        )
    url = project.read_text(contract.SOURCE_URL).strip()
    if not url:
        raise ContractError(f"{contract.SOURCE_URL} is empty in {project.dir}")
    tcfg = _transcribe_cfg(cfg)

    # Resume-friendly: a crash after download but before transcription
    # leaves the audio reusable.
    audio = None if force else _existing_audio(project)
    download_meta: dict[str, Any] = {}
    if audio is None:
        audio, download_meta = _download_audio(project, url)

    # Heavy import stays inside run() so importing this module never loads
    # the model.
    from faster_whisper import WhisperModel

    text, transcribe_meta = _transcribe(WhisperModel, audio, tcfg)
    _write_report(project, url, audio, download_meta, transcribe_meta)
    # transcript.txt written last: it is the stage's done-marker.
    project.write_text(contract.TRANSCRIPT, text)


def _transcribe_cfg(cfg: dict) -> dict[str, Any]:
    tcfg = cfg.get("transcribe")
    if not isinstance(tcfg, dict):
        raise ContractError("config: 'transcribe' section is required for ingest")
    for key in ("model", "device", "compute_type"):
        if key not in tcfg:
            raise ContractError(f"config: transcribe.{key} is required for ingest")
    return tcfg


# yt-dlp downloads to source_audio.<ext>.part (plus a .ytdl state file) and
# renames only on completion; a crash mid-download leaves those behind and
# they must never be mistaken for finished audio.
_PARTIAL_SUFFIXES = {".part", ".ytdl"}


def _existing_audio(project: Project) -> Path | None:
    matches = sorted(
        p for p in project.dir.glob(f"{AUDIO_STEM}.*")
        if p.suffix.lower() not in _PARTIAL_SUFFIXES
    )
    return matches[0] if matches else None


def _download_audio(project: Project, url: str) -> tuple[Path, dict[str, Any]]:
    import yt_dlp  # local: keep module import light

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(project.dir / f"{AUDIO_STEM}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except Exception as exc:
        raise StageError(STAGE, f"audio download failed for {url}: {exc}") from exc
    audio = _existing_audio(project)
    if audio is None:
        raise StageError(
            STAGE, f"yt-dlp finished but wrote no {AUDIO_STEM}.* file"
        )
    meta = {
        key: info.get(key)
        for key in ("title", "duration", "uploader")
        if info.get(key) is not None
    }
    return audio, meta


def _transcribe(
    model_cls: Any, audio: Path, tcfg: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    try:
        model = model_cls(
            tcfg["model"],
            device=tcfg["device"],
            compute_type=tcfg["compute_type"],
        )
        # No language argument: auto-detect.
        segments, info = model.transcribe(str(audio))
        paragraphs, n_segments = _group_paragraphs(segments)
    except Exception as exc:
        raise StageError(STAGE, f"transcription failed: {exc}") from exc
    if not paragraphs:
        raise StageError(STAGE, "transcription produced no text")

    meta: dict[str, Any] = {"segments": n_segments}
    language = getattr(info, "language", None)
    if language:
        meta["language"] = language
    probability = getattr(info, "language_probability", None)
    if probability is not None:
        meta["language_probability"] = probability
    return "\n\n".join(paragraphs) + "\n", meta


def _group_paragraphs(segments: Any) -> tuple[list[str], int]:
    """Join segment texts; a long silence gap starts a new paragraph."""
    paragraphs: list[str] = []
    current: list[str] = []
    prev_end: float | None = None
    n_segments = 0
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        n_segments += 1
        start = getattr(seg, "start", None)
        if (
            current
            and prev_end is not None
            and isinstance(start, (int, float))
            and start - prev_end > _PARAGRAPH_GAP_S
        ):
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        end = getattr(seg, "end", None)
        if isinstance(end, (int, float)):
            prev_end = end
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs, n_segments


def _write_report(
    project: Project,
    url: str,
    audio: Path,
    download_meta: dict[str, Any],
    transcribe_meta: dict[str, Any],
) -> None:
    report: dict[str, Any] = {}
    # When the download was skipped (audio reused), keep the metadata the
    # original download recorded instead of clobbering it.
    if project.has(INGEST_REPORT):
        existing = project.read_json(INGEST_REPORT)
        if isinstance(existing, dict):
            report = existing
    report["source_url"] = url
    report["audio_file"] = audio.name
    report.update(download_meta)
    report.update(transcribe_meta)
    project.write_json(INGEST_REPORT, report)
