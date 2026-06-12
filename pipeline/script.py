"""Script stage: transcript.txt -> script.json (thin wrapper).

The actual writing is done by Claude Code via the video-script skill —
generation is deliberately NOT automated here (PLAN.md: originality comes
from a supervised rewrite of the idea, never a mechanical paraphrase).
This stage only verifies that script.json exists and matches the frozen
contract shape, so the orchestrator stops with clear instructions when
the script has not been written yet.
"""

from __future__ import annotations

from pipeline import contract
from pipeline.contract import Project
from pipeline.errors import StageError

STAGE = "script"


def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None:
    """Check script.json exists and validates; never generates it."""
    # force has no effect: there is nothing to regenerate from here.
    if not project.has(contract.SCRIPT):
        raise StageError(
            STAGE,
            f"{contract.SCRIPT} not written yet — generate it with the "
            "video-script skill in Claude Code, then re-run",
        )
    # Always validate, even when the file exists: an invalid script must
    # stop the pipeline before voice spends money on it. Raises
    # ContractError (a contract violation, not a runtime failure).
    project.script()
