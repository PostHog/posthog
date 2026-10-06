"""The version marker of one review turn: the ReviewHog release plus a fingerprint of the turn's inputs.

`REVIEWHOG_VERSIONS` names one release per review mode and design (each evolves separately) and
changes only with a manual bump. The fingerprint is a short hash of everything else that decides how
one turn reviews: the review mode, the model pins of every stage, the prompt texts, and the content
of the skills the acting user runs (a team's own edited skill rows included). A single-agent turn
hashes its own prompt files and the dedup stage it still runs instead of the pipeline's prompts and
skills. A prompt edit or a skill edit changes the fingerprint without a
version bump, so production data can be split by "reviewhog-flash-1-0 with inputs Y".
"""

from __future__ import annotations

import json
import hashlib
from typing import Any

from django.db.models import Q

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
    REVIEW_DESIGN_PIPELINE,
    REVIEW_DESIGN_SINGLE_AGENT,
    ReviewArm,
    resolve_review_arm,
    review_arm_for_mode,
    reviewhog_version_for_mode,
    validation_arm_for_mode,
)
from products.review_hog.backend.reviewer.models import PROMPTS_DIR
from products.review_hog.backend.reviewer.sandbox.executor import JSON_RETRY_PROMPT
from products.review_hog.backend.reviewer.skill_loader import (
    load_blind_spots_skill_for_run,
    load_perspectives_for_run,
    load_validation_skill_for_run,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import DEDUP_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.issue_validation import (
    VALIDATION_FOLLOWUP_TEMPLATE,
    VALIDATION_SYSTEM_PROMPT,
)
from products.review_hog.backend.reviewer.tools.issues_review import REVIEW_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.select_perspectives import SELECTION_SYSTEM_PROMPT
from products.review_hog.backend.reviewer.tools.single_agent_review import SINGLE_AGENT_CORE_FILE
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import CHUNKING_SYSTEM_PROMPT
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

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

# Hard-coded prompt text a turn sends outside the system prompts and the prompt directories.
_REVIEW_TURN_EXTRA_PROMPTS = {
    "issue_validation/followup": VALIDATION_FOLLOWUP_TEMPLATE,
    "sandbox/json_retry": JSON_RETRY_PROMPT,
}

# The prompt directories a single-agent turn renders: its own review, then the shared dedup stage.
_SINGLE_AGENT_TURN_PROMPT_DIRS = (
    "single_agent_review",
    "issue_deduplicator",
)

FINGERPRINT_LENGTH = 7

_SKILL_FILE_CHUNK_SIZE = 20


@frozen
class ReviewHogMarker:
    """The version id (`reviewhog-flash-1-0`) and input fingerprint one turn ran with."""

    version: str
    fingerprint: str

    def hidden_comment(self) -> str:
        # An HTML comment, so the status comment carries the marker without adding visible text.
        return f"<!-- reviewhog-version: {self.version} {self.fingerprint} -->"


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
    def _prompt_dir_hashes(prompt_dirs: tuple[str, ...]) -> dict[str, str]:
        return {
            f"{prompt_dir}/{filename}": _text_hash((PROMPTS_DIR / prompt_dir / filename).read_text())
            for prompt_dir in prompt_dirs
            for filename in ("prompt.jinja", "schema.json")
        }

    @classmethod
    def _prompt_hashes(cls) -> dict[str, str]:
        hashes = {f"{name}/system": _text_hash(text) for name, text in _REVIEW_TURN_SYSTEM_PROMPTS.items()}
        hashes.update({name: _text_hash(text) for name, text in _REVIEW_TURN_EXTRA_PROMPTS.items()})
        hashes.update(cls._prompt_dir_hashes(_REVIEW_TURN_PROMPT_DIRS))
        return hashes

    @classmethod
    def _single_agent_prompt_hashes(cls) -> dict[str, str]:
        hashes = cls._prompt_dir_hashes(_SINGLE_AGENT_TURN_PROMPT_DIRS)
        # The whole file, attribution comment included, so any edit to it changes the fingerprint.
        hashes["single_agent_review/core.md"] = _text_hash(SINGLE_AGENT_CORE_FILE.read_text())
        hashes["issue_deduplicator/system"] = _text_hash(DEDUP_SYSTEM_PROMPT)
        hashes["sandbox/json_retry"] = _text_hash(JSON_RETRY_PROMPT)
        return hashes

    @staticmethod
    def _skill_hashes(team_id: int, acting_user_id: int) -> dict[str, str]:
        pinned = [(p.skill_name, p.version) for p in load_perspectives_for_run(team_id, acting_user_id)]
        blind_spots = load_blind_spots_skill_for_run(team_id, acting_user_id)
        validation = load_validation_skill_for_run(team_id, acting_user_id)
        pinned.append((blind_spots.skill_name, blind_spots.version))
        pinned.append((validation.skill_name, validation.version))
        pinned_filter = Q()
        for skill_name, version in pinned:
            pinned_filter |= Q(name=skill_name, version=version)
        # An archived row can share name and version with a live one; only the live row is unique.
        skills = list(LLMSkill.objects.filter(pinned_filter, team_id=team_id, deleted=False))
        names = {skill.id: skill.name for skill in skills}
        # Every field `skill-get` returns to the agent, but not the version number: the same
        # content on two teams gives the same hash.
        hashers = {
            skill.id: hashlib.sha256(
                json.dumps(
                    [
                        skill.description,
                        skill.body,
                        skill.license,
                        skill.compatibility,
                        sorted(skill.allowed_tools or []),
                        skill.metadata or {},
                    ],
                    sort_keys=True,
                ).encode()
            )
            for skill in skills
        }
        # A custom skill can bundle many large files, so stream them into the hash one at a time.
        files = (
            LLMSkillFile.objects.filter(skill_id__in=list(hashers))
            .order_by("skill_id", "path")
            .values_list("skill_id", "path", "content_type", "content")
            .iterator(chunk_size=_SKILL_FILE_CHUNK_SIZE)
        )
        for skill_id, path, content_type, content in files:
            hashers[skill_id].update(json.dumps([path, content_type, content]).encode())
        return {names[skill_id]: hasher.hexdigest() for skill_id, hasher in hashers.items()}

    @classmethod
    def for_turn(
        cls,
        *,
        team_id: int,
        report: ReviewReport,
        acting_user_id: int,
        review_mode: str,
        flash_reasoning_effort: str,
        review_design: str = REVIEW_DESIGN_PIPELINE,
    ) -> TurnFingerprint:
        stored_arm = resolve_review_arm(
            report.review_runtime_adapter,
            report.review_model,
            report.review_reasoning_effort,
            report.review_initial_permission_mode,
        )
        review_arm = review_arm_for_mode(
            review_mode, stored_arm, flash_reasoning_effort=flash_reasoning_effort, review_design=review_design
        )
        if review_design == REVIEW_DESIGN_SINGLE_AGENT:
            return cls(
                {
                    "review_mode": review_mode,
                    "review_design": review_design,
                    "review_arm": _arm_payload(review_arm),
                    "stage_pins": cls._stage_pins(),
                    "prompts": cls._single_agent_prompt_hashes(),
                }
            )
        validation_arm = validation_arm_for_mode(review_mode, flash_reasoning_effort=flash_reasoning_effort)
        return cls(
            {
                "review_mode": review_mode,
                "review_arm": _arm_payload(review_arm),
                "validation_arm": _arm_payload(validation_arm),
                "stage_pins": cls._stage_pins(),
                "prompts": cls._prompt_hashes(),
                # The workflow's team, not `report.team_id`: the report stores a child environment's
                # parent team, but the skill sync and the stage loaders read the environment's own rows.
                "skills": cls._skill_hashes(team_id, acting_user_id),
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
    review_design: str = REVIEW_DESIGN_PIPELINE,
) -> ReviewHogMarker:
    """Compute the turn's marker and persist it as the turn's `turn_marker` artefact."""
    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    fingerprint = TurnFingerprint.for_turn(
        team_id=team_id,
        report=report,
        acting_user_id=acting_user_id,
        review_mode=review_mode,
        flash_reasoning_effort=flash_reasoning_effort,
        review_design=review_design,
    )
    marker = ReviewHogMarker(
        version=reviewhog_version_for_mode(review_mode, review_design), fingerprint=fingerprint.digest()
    )
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
