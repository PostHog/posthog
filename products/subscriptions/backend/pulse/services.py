"""Pure validation, snapshot, fingerprint, and history helpers for Pulse."""

import json
from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from .contracts import (
    ActionKind,
    GoalNormalizationCandidate,
    GoalNormalizationInput,
    GoalNormalizationResult,
    ProactiveConfigInput,
)

GOAL_NORMALIZATION_PROMPT_VERSION = "v1"
MAX_GOAL_STATEMENT_CHARS = 1000
MAX_DECISION_CONSTRAINTS = 8
MAX_SNAPSHOT_PROMPT_CHARS = 4000
MAX_SNAPSHOT_CONTEXTS = 3
SNAPSHOT_LIMIT_CAPS = {
    "max_actions": 3,
    "max_tool_calls": 20,
    "max_public_research_calls": 3,
    "max_runtime_seconds": 60 * 60,
}
SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS = frozenset({200_000, 1_000_000})
ALLOWED_SNAPSHOT_LIMITS = frozenset({*SNAPSHOT_LIMIT_CAPS, "max_agent_context_tokens"})
ALLOWED_SNAPSHOT_FLAGS = frozenset({"allow_draft_pr", "allow_experiment_draft", "allow_public_research"})


def validate_snapshot_fields(
    *, original_prompt: str, contexts: list[dict[str, int]], limits: dict[str, int], flags: dict[str, bool]
) -> None:
    if not original_prompt or len(original_prompt) > MAX_SNAPSHOT_PROMPT_CHARS:
        raise ValueError("original_prompt must be non-empty and bounded")
    if len(contexts) > MAX_SNAPSHOT_CONTEXTS:
        raise ValueError("contexts exceed the subscription limit")
    for context in contexts:
        if set(context) not in ({"dashboard_id"}, {"insight_id"}) or any(
            not isinstance(value, int) or value < 1 for value in context.values()
        ):
            raise ValueError("contexts must contain exactly one positive dashboard_id or insight_id")
    if set(limits) - ALLOWED_SNAPSHOT_LIMITS or any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or (key == "max_agent_context_tokens" and value not in SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS)
        or (key in SNAPSHOT_LIMIT_CAPS and value > SNAPSHOT_LIMIT_CAPS[key])
        for key, value in limits.items()
    ):
        raise ValueError("limits contain an invalid key or value")
    if set(flags) - ALLOWED_SNAPSHOT_FLAGS or any(not isinstance(value, bool) for value in flags.values()):
        raise ValueError("flags contain an invalid key or value")


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(encoded).hexdigest()


def opportunity_fingerprint(*, observation_targets: dict[str, Any], evidence_ids: Iterable[str]) -> str:
    """Return a team-wide identity without subscription or model-authored prose."""
    return _canonical_fingerprint(
        {"version": "v1", "observation_targets": observation_targets, "evidence_ids": sorted(set(evidence_ids))}
    )


def action_fingerprint(
    *, goal_statement: str, kind: str, normalized_target: dict[str, Any], evidence_ids: Iterable[str]
) -> str:
    """Return a run-action identity that remains specific to the current goal."""
    return _canonical_fingerprint(
        {
            "version": "v1",
            "goal_statement": goal_statement,
            "kind": kind,
            "normalized_target": normalized_target,
            "evidence_ids": sorted(set(evidence_ids)),
        }
    )


def stable_action_key(*, kind: ActionKind, normalized_target: dict[str, str], metric_name: str) -> str:
    """Return a cross-run proposal identity without model-authored prose or evidence."""
    normalized_metric_name = " ".join(metric_name.split()).casefold()
    if not normalized_metric_name or any(
        not key or not isinstance(value, str) for key, value in normalized_target.items()
    ):
        raise ValueError("Stable action identity requires a metric and string target values.")
    return _canonical_fingerprint(
        {
            "version": "v1",
            "kind": kind,
            "normalized_target": dict(sorted(normalized_target.items())),
            "metric_name": normalized_metric_name,
        }
    )


def fallback_goal_normalization(original_prompt: str, *, model_version: str | None = None) -> GoalNormalizationResult:
    bounded_prompt = " ".join(original_prompt.split())[:MAX_GOAL_STATEMENT_CHARS]
    return GoalNormalizationResult(
        goal_statement=bounded_prompt,
        decision_constraints=[],
        prompt_version=GOAL_NORMALIZATION_PROMPT_VERSION,
        model_version=model_version,
        valid=False,
        failure_code="goal_normalization_failed",
    )


def validate_goal_normalization(
    candidate: GoalNormalizationCandidate, source: GoalNormalizationInput, *, model_version: str | None = None
) -> GoalNormalizationResult:
    if (
        not set(candidate.repositories).issubset(source.repositories)
        or not set(candidate.identities).issubset(source.identities)
        or not set(candidate.metrics).issubset(source.metrics)
        or not set(candidate.artifact_types).issubset(source.artifact_types)
        or not set(candidate.permissions).issubset(source.permissions)
    ):
        return GoalNormalizationResult(
            goal_statement=fallback_goal_normalization(source.original_prompt).goal_statement,
            decision_constraints=[],
            prompt_version=GOAL_NORMALIZATION_PROMPT_VERSION,
            model_version=model_version,
            valid=False,
            failure_code="goal_normalization_widened_consent",
        )
    goal_statement = " ".join(candidate.goal_statement.split())[:MAX_GOAL_STATEMENT_CHARS]
    if not goal_statement:
        return fallback_goal_normalization(source.original_prompt)
    constraints = [" ".join(item.split())[:240] for item in candidate.decision_constraints if item.strip()]
    return GoalNormalizationResult(
        goal_statement=goal_statement,
        decision_constraints=constraints[:MAX_DECISION_CONSTRAINTS],
        prompt_version=GOAL_NORMALIZATION_PROMPT_VERSION,
        model_version=model_version,
        valid=True,
    )


def validate_proactive_config_input(
    config: ProactiveConfigInput,
    *,
    resource_type: str,
    repository_authorized: bool,
    subject: Any | None,
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    repository = config.repository.strip().lower() if config.repository else None
    if resource_type != "ai_prompt" and (config.enabled or repository or config.create_draft_pr):
        errors["enabled"] = ["Proactive follow-up only applies to AI report subscriptions."]
    if config.create_draft_pr:
        if not config.enabled:
            errors["create_draft_pr"] = ["Enable proactive follow-up before allowing draft pull requests."]
        if not repository:
            errors["repository"] = ["Choose one repository before allowing draft pull requests."]
        if not repository_authorized:
            errors["repository"] = ["This repository is not currently authorized for draft pull requests."]
    if config.public_research_subject_id is not None and (
        subject is None
        or not getattr(subject, "eligible", False)
        or getattr(subject, "reviewed_at", None) is None
        or getattr(subject, "disabled_at", None) is not None
    ):
        errors["public_research_subject_id"] = ["Choose an eligible reviewed public research subject for this project."]
    return errors
