"""Publish stage: script.json -> post.json (metadata only; never posts).

Builds the title/description/hashtags payload a human pastes when posting
manually. Two defenses are baked in: a banned engagement-bait phrase list
(pipeline/banned_phrases_ar.txt, PLAN.md 3.1) that fails the stage loudly,
and a hard refusal to run with publish.auto_post enabled (PLAN.md 3.6 —
manual posting until the format is proven).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from pipeline import contract
from pipeline.contract import ContractError

STAGE = "publish"

_PHRASES_PATH = Path(__file__).with_name("banned_phrases_ar.txt")

# Tashkeel/Quranic marks + tatweel: presentation-only, stripped pre-match.
_ARABIC_MARKS = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۭـ]"
)
_LETTER_FOLDS = (("أ", "ا"), ("إ", "ا"),  # أ إ -> ا
                 ("آ", "ا"), ("ٱ", "ا"),  # آ ٱ -> ا
                 ("ى", "ي"),                        # ى -> ي
                 ("ة", "ه"))                        # ة -> ه


# --------------------------------------------------------------------------
# Stage entry point
# --------------------------------------------------------------------------

def run(project: contract.Project, cfg: dict, env: dict, *,
        force: bool = False) -> None:
    # Checked before the idempotency guard: this stage must fail loudly the
    # moment anyone flips the flag, output on disk or not.
    if (cfg.get("publish") or {}).get("auto_post"):
        raise ContractError(
            "auto-posting is disabled by design until the format is proven "
            "— see PLAN.md 3.6"
        )
    if not force and project.has(contract.POST):
        return
    if not project.has(contract.SCRIPT):
        # Missing contracted input = contract violation (consistent with
        # ingest/render).
        raise ContractError(
            f"{contract.SCRIPT} not found — run the script stage first"
        )
    post = project.script()["post"]
    hashtags = [str(h) for h in post["hashtags"]]
    hits = _banned_hits({
        "title": post["title"],
        "description": post["description"],
        "hashtags": " ".join(hashtags),
    })
    if hits:
        raise ContractError(
            "post metadata contains banned engagement-bait phrases — "
            + "; ".join(hits)
        )

    runtime = None
    if project.has(contract.TIMING):
        runtime = project.timing()["total_seconds"]
    project.write_json(contract.POST, {
        "title": post["title"],
        "description": post["description"],
        "hashtags": hashtags,
        "needs_ai_label": bool((cfg.get("footage") or {}).get("ai_broll",
                                                              False)),
        "runtime_seconds": runtime,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    })


# --------------------------------------------------------------------------
# Banned-phrase defense
# --------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _ARABIC_MARKS.sub("", text)
    for src, dst in _LETTER_FOLDS:
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _load_banned_phrases() -> list[str]:
    if not _PHRASES_PATH.exists():
        raise ContractError(
            f"{_PHRASES_PATH.name} is missing from pipeline/ — the "
            f"engagement-bait defense must exist before publish runs"
        )
    phrases = [
        line.strip()
        for line in _PHRASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not phrases:
        raise ContractError(f"{_PHRASES_PATH.name} contains no phrases")
    return phrases


def _banned_hits(fields: dict[str, str]) -> list[str]:
    """Every (field, phrase) hit, as human-readable strings."""
    normalized = {field: _normalize(text) for field, text in fields.items()}
    hits: list[str] = []
    for phrase in _load_banned_phrases():
        norm = _normalize(phrase)
        if not norm:
            continue
        # Word-boundary-anchored substring: catches bait anywhere in the
        # text without flagging longer words (يشير/تشير must not match شير).
        pattern = re.compile(rf"(?<!\w){re.escape(norm)}(?!\w)")
        for field, text in normalized.items():
            if pattern.search(text):
                hits.append(f"{field} contains '{phrase}'")
    return hits
