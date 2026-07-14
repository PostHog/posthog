"""Central AI run defaults for task runs.

Resolves the effective `(runtime_adapter, model, reasoning_effort)` triple for a
new task run from, in order: explicit per-run values, the acting user's
per-project preference (`UserTasksConfig`), and the project default
(`TeamTasksConfig`). Surfaces with their own preference layer (e.g. the Slack
app's per-workspace/per-user settings) resolve first and pass the result as
explicit values, which naturally places them above the central preferences.

Resolution is a whole-triple swap, not a field-by-field merge: if a level
carries the atomic `(runtime_adapter, model)` pair, that level's entire
preference object wins (including its absent `reasoning_effort`). A
field-by-field merge would blend mismatched configurations — for example a
team `reasoning_effort` glued onto the user's non-thinking model — which is
never what anyone picked. Mirrors the Slack app's `resolve_ai_preferences`.

Lenient at resolve time by design: preferences are stored as raw ids and the
available model list drifts as the LLM gateway evolves, so an unknown model id
passes through (the agent server owns the final fallback), a triple whose
runtime adapter is no longer valid is skipped in favor of the next level, and
a reasoning effort the resolved model doesn't support is dropped. This module
never raises during resolution.
"""

from dataclasses import dataclass
from typing import Any, Literal

from django.core.exceptions import ValidationError

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team

from products.tasks.backend.models import TeamTasksConfig, UserTasksConfig
from products.tasks.backend.temporal.process_task.utils import (
    PUBLIC_REASONING_EFFORTS,
    RuntimeAdapter,
    get_reasoning_effort_error,
    get_supported_reasoning_efforts,
)


@dataclass(frozen=True)
class ResolvedAIRunConfig:
    """The effective AI run triple plus which preference level supplied it."""

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    source: Literal["explicit", "user", "team", "none"] = "none"


def resolve_ai_run_selection(
    team_id: int,
    user_id: int | None,
    *,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> ResolvedAIRunConfig:
    """The effective runtime selection for a new run: the caller's own selection when it
    pins anything, otherwise the stored defaults.

    A partial pin (either `runtime_adapter` or `model` alone) is treated as explicit and
    returned untouched — filling in the other half from a preference would pair values
    the caller never chose together. When defaults apply, an explicitly passed
    `reasoning_effort` survives and the default triple's effort only fills a gap.
    """
    if runtime_adapter or model:
        return ResolvedAIRunConfig(
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
            source="explicit",
        )

    resolved = resolve_ai_run_defaults(team_id, user_id)
    if not (resolved.runtime_adapter and resolved.model):
        return ResolvedAIRunConfig(reasoning_effort=reasoning_effort, source="none")
    return ResolvedAIRunConfig(
        runtime_adapter=resolved.runtime_adapter,
        model=resolved.model,
        reasoning_effort=reasoning_effort or resolved.reasoning_effort,
        source=resolved.source,
    )


def resolve_ai_run_defaults(team_id: int, user_id: int | None) -> ResolvedAIRunConfig:
    """The stored default AI run triple: the acting user's per-project preference wins
    wholesale, then the project default, then empty."""
    canonical_team_id = resolve_effective_team_id(team_id)

    if user_id is not None:
        user_prefs = (
            UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
            .filter(user_id=user_id)
            .values_list("ai_run_preferences", flat=True)
            .first()
        )
        resolved = _resolve_from_preferences(user_prefs, source="user")
        if resolved is not None:
            return resolved

    team_prefs = (
        TeamTasksConfig.objects.filter(team_id=canonical_team_id).values_list("ai_run_preferences", flat=True).first()
    )
    resolved = _resolve_from_preferences(team_prefs, source="team")
    if resolved is not None:
        return resolved

    return ResolvedAIRunConfig(source="none")


def _resolve_from_preferences(
    preferences: dict[str, Any] | None, *, source: Literal["user", "team"]
) -> ResolvedAIRunConfig | None:
    """A `ResolvedAIRunConfig` from a stored preference payload, or `None` when the
    payload carries no usable `(runtime_adapter, model)` pair (fall through to the
    next level)."""
    prefs = preferences or {}
    runtime_adapter = prefs.get("runtime_adapter") or None
    model = prefs.get("model") or None
    reasoning_effort = prefs.get("reasoning_effort") or None

    if not (runtime_adapter and model):
        return None
    # A stored adapter the registry no longer knows can't pick a harness; skip the level.
    if runtime_adapter not in {a.value for a in RuntimeAdapter}:
        return None
    if reasoning_effort is not None:
        reasoning_effort = _filter_unsupported_effort(runtime_adapter, model, reasoning_effort)

    return ResolvedAIRunConfig(
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
        source=source,
    )


def _filter_unsupported_effort(runtime_adapter: str, model: str, effort: str) -> str | None:
    """Drop a stored effort the resolved model no longer supports (e.g. saved
    `high` on a thinking model, then the preference's model changed)."""
    supported = {e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)}
    return effort if effort in supported else None


def validate_ai_run_preferences(
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> None:
    """Validate the `(runtime_adapter, model, reasoning_effort)` triple on the write
    path so half-set rows never reach the DB.

    Strict on structure (pair set together, known adapter and effort, effort/model
    compatibility) but deliberately not on model-id membership — the gateway's
    model list drifts, and resolution handles stale ids leniently.

    Raises `django.core.exceptions.ValidationError` on inconsistency.
    """
    if (runtime_adapter is None) != (model is None):
        raise ValidationError(
            "runtime_adapter and model must be set together — set both to configure a default, or both to null to clear it."
        )

    if runtime_adapter is not None:
        valid_adapters = {a.value for a in RuntimeAdapter}
        if runtime_adapter not in valid_adapters:
            raise ValidationError(
                f"Unknown runtime_adapter '{runtime_adapter}'. Valid: {', '.join(sorted(valid_adapters))}."
            )

    if reasoning_effort is not None:
        valid_efforts = {e.value for e in PUBLIC_REASONING_EFFORTS}
        if reasoning_effort not in valid_efforts:
            raise ValidationError(
                f"Unknown reasoning_effort '{reasoning_effort}'. Valid: {', '.join(sorted(valid_efforts))}."
            )

    error = get_reasoning_effort_error(runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort)
    if error:
        raise ValidationError(error)


def build_ai_run_preferences_payload(
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, str]:
    """Pack the triple into the JSON shape stored on `ai_run_preferences`.

    Drops keys whose value is falsy so a cleared preference is stored as an
    empty object rather than a triple of nulls.
    """
    payload = {
        "runtime_adapter": runtime_adapter,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }
    return {k: v for k, v in payload.items() if v}


def get_team_ai_run_preferences(team_id: int) -> dict[str, str]:
    """The stored team-level preference payload ({} when unset)."""
    prefs = (
        TeamTasksConfig.objects.filter(team_id=resolve_effective_team_id(team_id))
        .values_list("ai_run_preferences", flat=True)
        .first()
    )
    return dict(prefs or {})


def update_team_ai_run_preferences(
    team_id: int,
    *,
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, str]:
    """Validate and store the team-level preference triple; returns the stored payload.

    Raises `django.core.exceptions.ValidationError` on an inconsistent triple.
    """
    validate_ai_run_preferences(runtime_adapter, model, reasoning_effort)
    payload = build_ai_run_preferences_payload(runtime_adapter, model, reasoning_effort)
    team = Team.objects.get(id=resolve_effective_team_id(team_id))
    config = get_or_create_team_extension(team, TeamTasksConfig)
    config.ai_run_preferences = payload
    config.save(update_fields=["ai_run_preferences", "updated_at"])
    return payload


def get_user_ai_run_preferences(team_id: int, user_id: int) -> dict[str, str]:
    """The stored per-(user, project) preference payload ({} when unset)."""
    canonical_team_id = resolve_effective_team_id(team_id)
    prefs = (
        UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
        .filter(user_id=user_id)
        .values_list("ai_run_preferences", flat=True)
        .first()
    )
    return dict(prefs or {})


def update_user_ai_run_preferences(
    team_id: int,
    user_id: int,
    *,
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, str]:
    """Validate and upsert the per-(user, project) preference triple; returns the stored
    payload. Raises `django.core.exceptions.ValidationError` on an inconsistent triple.
    """
    validate_ai_run_preferences(runtime_adapter, model, reasoning_effort)
    payload = build_ai_run_preferences_payload(runtime_adapter, model, reasoning_effort)
    canonical_team_id = resolve_effective_team_id(team_id)
    # team_id repeated in the lookup kwargs: for_team() only filters reads — creation
    # needs the value passed explicitly.
    UserTasksConfig.objects.for_team(canonical_team_id, canonical=True).update_or_create(
        team_id=canonical_team_id,
        user_id=user_id,
        defaults={"ai_run_preferences": payload},
    )
    return payload


__all__ = [
    "ResolvedAIRunConfig",
    "build_ai_run_preferences_payload",
    "get_team_ai_run_preferences",
    "get_user_ai_run_preferences",
    "resolve_ai_run_defaults",
    "resolve_ai_run_selection",
    "update_team_ai_run_preferences",
    "update_user_ai_run_preferences",
    "validate_ai_run_preferences",
]
