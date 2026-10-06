"""The version marker of one review turn: the ReviewHog release plus a fingerprint of the turn's inputs.

`REVIEWHOG_VERSION` names a release and changes only with a manual bump. The fingerprint is a short
hash of everything else that decides how one turn reviews: the review mode, the model pins of every
stage, the prompt texts, and the content of the skills the acting user runs (a team's own edited
skill rows included). A prompt edit or a skill edit changes the fingerprint without a version bump,
so production data can be split by "ReviewHog at version X with inputs Y".
"""

from __future__ import annotations

import json
import hashlib
from typing import Any

from posthog.dataclasses import frozen

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.constants import (
    CHUNKING_MODEL,
    CHUNKING_REASONING_EFFORT,
    CHUNKING_RUNTIME_ADAPTER,
    DEDUP_MODEL,
    DEDUP_REASONING_EFFORT,
    DEDUP_RUNTIME_ADAPTER,
    ONESHOT_MODEL,
    ONESHOT_REASONING_EFFORT,
    REVIEWHOG_VERSION,
    ReviewArm,
    resolve_review_arm,
    review_arm_for_mode,
    validation_arm_for_mode,
)
from products.review_hog.backend.reviewer.lazy_seed import compute_skill_row_hash
from products.review_hog.backend.reviewer.models import PROMPTS_DIR
from products.review_hog.backend.reviewer.skill_loader import (
    load_blind_spots_skill_for_run,
    load_perspectives_for_run,
    load_validation_skill_for_run,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import DEDUP_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.issue_validation import VALIDATION_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.issues_review import REVIEW_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.select_perspectives import SELECTION_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import CHUNKING_SYSTEM_PROMPT
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.skills.backend.models.skills import LLMSkill

# The prompt directories a review turn renders. `thread_resolution` is left out: the resolution
# stage runs as its own workflow after the turn, not as part of it.
_REVIEW_TURN_PROMPT_DIRS = (
    "chunking",
    "perspective_selection",
    "issues_review",
    "issue_deduplicator",
    "issue_validation",
)

_REVIEW_TURN_SYSTEM_PROMPTS = {
    "chunking": CHUNKING_SYSTEM_PROMPT,
    "perspective_selection": SELECTION_SYSTEM_PROMPT,
    "issues_review": REVIEW_SYSTEM_PROMPT,
    "issue_deduplicator": DEDUP_SYSTEM_PROMPT,
    "issue_validation": VALIDATION_SYSTEM_PROMPT,
}

FINGERPRINT_LENGTH = 7


@frozen
class ReviewHogMarker:
    """The release version and input fingerprint one turn ran with."""

    version: str
    fingerprint: str

    def label(self) -> str:
        return f"ReviewHog {self.version} · {self.fingerprint}"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _arm_payload(arm: ReviewArm) -> dict[str, str | None]:
    return {
        "runtime_adapter": arm.runtime_adapter.value,
        "model": arm.model,
        "reasoning_effort": arm.reasoning_effort.value,
        "initial_permission_mode": arm.initial_permission_mode,
    }


class TurnFingerprint:
    """The inputs that decide how one turn reviews, and their short hash."""

    def __init__(self, inputs: dict[str, Any]) -> None:
        self.inputs = inputs

    @staticmethod
    def _stage_pins() -> dict[str, dict[str, str]]:
        # Chunking and dedup pick the one-shot or the sandbox path by input size, so both pins count.
        return {
            "oneshot": {"model": ONESHOT_MODEL, "reasoning_effort": ONESHOT_REASONING_EFFORT},
            "chunking_sandbox": {
                "runtime_adapter": CHUNKING_RUNTIME_ADAPTER.value,
                "model": CHUNKING_MODEL,
                "reasoning_effort": CHUNKING_REASONING_EFFORT.value,
            },
            "dedup_sandbox": {
                "runtime_adapter": DEDUP_RUNTIME_ADAPTER.value,
                "model": DEDUP_MODEL,
                "reasoning_effort": DEDUP_REASONING_EFFORT.value,
            },
        }

    @staticmethod
    def _prompt_hashes() -> dict[str, str]:
        hashes = {f"{name}/system": _text_hash(text) for name, text in _REVIEW_TURN_SYSTEM_PROMPTS.items()}
        for prompt_dir in _REVIEW_TURN_PROMPT_DIRS:
            for filename in ("prompt.jinja", "schema.json"):
                hashes[f"{prompt_dir}/{filename}"] = _text_hash((PROMPTS_DIR / prompt_dir / filename).read_text())
        return hashes

    @staticmethod
    def _skill_hashes(team_id: int, acting_user_id: int) -> dict[str, str]:
        pinned = [(p.skill_name, p.version) for p in load_perspectives_for_run(team_id, acting_user_id)]
        blind_spots = load_blind_spots_skill_for_run(team_id, acting_user_id)
        validation = load_validation_skill_for_run(team_id, acting_user_id)
        pinned.append((blind_spots.skill_name, blind_spots.version))
        pinned.append((validation.skill_name, validation.version))
        hashes: dict[str, str] = {}
        for skill_name, version in pinned:
            skill = LLMSkill.objects.prefetch_related("files").get(team_id=team_id, name=skill_name, version=version)
            # Content only, not the version number: the same text on two teams gives the same hash.
            hashes[skill_name] = compute_skill_row_hash(skill, list(skill.files.all()))
        return hashes

    @classmethod
    def for_turn(
        cls, *, report: ReviewReport, acting_user_id: int, review_mode: str, flash_reasoning_effort: str
    ) -> TurnFingerprint:
        stored_arm = resolve_review_arm(
            report.review_runtime_adapter,
            report.review_model,
            report.review_reasoning_effort,
            report.review_initial_permission_mode,
        )
        review_arm = review_arm_for_mode(review_mode, stored_arm, flash_reasoning_effort=flash_reasoning_effort)
        validation_arm = validation_arm_for_mode(review_mode, flash_reasoning_effort=flash_reasoning_effort)
        return cls(
            {
                "review_mode": review_mode,
                "review_arm": _arm_payload(review_arm),
                "validation_arm": _arm_payload(validation_arm),
                "stage_pins": cls._stage_pins(),
                "prompts": cls._prompt_hashes(),
                "skills": cls._skill_hashes(report.team_id, acting_user_id),
            }
        )

    def digest(self) -> str:
        return _text_hash(json.dumps(self.inputs, sort_keys=True))[:FINGERPRINT_LENGTH]


def record_turn_marker(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    run_index: int,
    acting_user_id: int,
    review_mode: str,
    flash_reasoning_effort: str,
) -> ReviewHogMarker:
    """Compute the turn's marker and persist it as the turn's `turn_marker` artefact."""
    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    fingerprint = TurnFingerprint.for_turn(
        report=report,
        acting_user_id=acting_user_id,
        review_mode=review_mode,
        flash_reasoning_effort=flash_reasoning_effort,
    )
    marker = ReviewHogMarker(version=REVIEWHOG_VERSION, fingerprint=fingerprint.digest())
    ReviewReportArtefact.add_turn_marker(
        team_id=team_id,
        report_id=report_id,
        content=TurnMarkerArtefact(
            head_sha=head_sha,
            run_index=run_index,
            review_mode=review_mode,
            reviewhog_version=marker.version,
            reviewhog_fingerprint=marker.fingerprint,
            fingerprint_inputs=fingerprint.inputs,
        ),
        attribution=ArtefactAttribution.system(),
    )
    return marker
