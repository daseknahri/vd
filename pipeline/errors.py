"""Stage failure type the orchestrator can report and continue past."""

from __future__ import annotations


class StageError(RuntimeError):
    """A pipeline stage failed at runtime (network, ffmpeg, provider...).

    In batch mode the orchestrator records it and moves on to the next
    project; contract violations (ContractError) stop the project instead.
    """

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"[{stage}] {message}")
