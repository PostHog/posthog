"""Read/write helpers for per-(Slack workspace, Slack user) settings backed
by `models.SlackSettings`. Exposes AI-preference resolution and the untagged
follow-up mode; future per-user / per-workspace knobs belong here too.

Key names mirror the task-run request serializer
(`products/tasks/backend/presentation/serializers.py`) so the resolver output
can be handed to the task layer with zero translation.

Resolution: AI preferences are a personal setting. Only the user's own row
counts, and only when it carries the atomic `(runtime_adapter, model)` pair —
a half-set row reads as "no preference" rather than half-applying.
`reasoning_effort` is dropped if the resolved model doesn't support it, so a
stale effort from a previous model choice can't silently stick. Unset keys
stay `None` so the task layer applies its own defaults rather than
duplicating them here.

Gated by the `slack-app-home` feature flag: when off the resolver returns
the empty object, preserving pre-Home-tab behaviour for workspaces that
haven't opted in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from products.slack_app.backend.feature_flags import is_slack_app_home_enabled
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.model_catalogue import filter_unsupported_effort

if TYPE_CHECKING:
    from posthog.models.integration import Integration


@dataclass(frozen=True)
class AIPreferences:
    """Resolved AI preferences for a single (workspace, slack_user_id) lookup.

    Field names match the task-run request serializer so callers can splat this
    straight into the task creation payload.
    """

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.runtime_adapter is None and self.model is None and self.reasoning_effort is None


_EMPTY = AIPreferences()


def resolve_ai_preferences(integration: Integration, slack_user_id: str | None) -> AIPreferences:
    """Resolve the effective AI preferences for a Slack user in a workspace.

    Only the user's own row counts, and only when it carries the atomic
    `(runtime_adapter, model)` pair. `reasoning_effort` is dropped if the
    resolved model doesn't support it.
    """

    if not slack_user_id or not is_slack_app_home_enabled(integration):
        return _EMPTY

    from products.slack_app.backend.models import SlackSettings

    row = (
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id,
            slack_user_id=slack_user_id,
        )
        .values("ai_preferences")
        .first()
    )
    # Pulled into a local dict so mypy can give it a definite type — the
    # JSONField reads back as `Any | None`.
    prefs: dict[str, Any] = (row["ai_preferences"] if row else None) or {}

    # `validate_ai_preferences` enforces that `runtime_adapter` and `model` are
    # set together, so a row missing either half was never explicitly
    # configured and contributes nothing.
    runtime_adapter = prefs.get("runtime_adapter") or None
    model = prefs.get("model") or None
    if not runtime_adapter or not model:
        return _EMPTY

    reasoning_effort = prefs.get("reasoning_effort") or None
    if reasoning_effort:
        reasoning_effort = filter_unsupported_effort(runtime_adapter, model, reasoning_effort)

    return AIPreferences(
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def resolve_untagged_followup_mode(integration: Integration, slack_user_id: str | None) -> UntaggedFollowupMode:
    """Resolve how untagged replies in a thread this Slack user started are treated.

    Read from the thread creator's row, so one person's choice governs every
    reply in the threads they started. An absent row, an empty column, or a
    value we no longer recognise all resolve to `NEVER`: the feature is opt-in,
    so nothing is picked up until someone asks for it.
    """

    if not slack_user_id:
        return UntaggedFollowupMode.NEVER

    from products.slack_app.backend.models import SlackSettings

    row = (
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id,
            slack_user_id=slack_user_id,
        )
        .values("untagged_followup_mode")
        .first()
    )
    stored = row["untagged_followup_mode"] if row else None
    if stored in UntaggedFollowupMode.values:
        return UntaggedFollowupMode(stored)
    return UntaggedFollowupMode.NEVER


def build_ai_preferences_payload(
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, str]:
    """Pack the triple into the JSON shape stored on `SlackSettings.ai_preferences`.

    Drops keys whose value is `None` so callers can distinguish "intentionally
    cleared" (key absent) from "set to falsy value".
    """
    payload = {
        "runtime_adapter": runtime_adapter,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }
    return {k: v for k, v in payload.items() if v}


def validate_ai_preferences(
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> None:
    """Validate the `(runtime_adapter, model, reasoning_effort)` triple.

    Raises `django.core.exceptions.ValidationError` if the triple is internally
    inconsistent. Call this from the write path so half-set rows never reach
    the DB. The storage rule — both halves of the pair or neither — lives here;
    whether the three values may be used together is the model catalogue's call.
    """
    from django.core.exceptions import ValidationError

    from products.tasks.backend.facade.run_config import PUBLIC_REASONING_EFFORTS, validate_model_selection

    if (runtime_adapter is None) != (model is None):
        raise ValidationError(
            "runtime_adapter and model must be set together — set both to override the default, or both to null to inherit."
        )

    # The catalogue only judges an effort against a model, so an effort stored without a
    # pair — legal, and inherited by whatever model resolves later — still needs a check.
    if reasoning_effort is not None:
        valid_efforts = {e.value for e in PUBLIC_REASONING_EFFORTS}
        if reasoning_effort not in valid_efforts:
            raise ValidationError(
                f"Unknown reasoning_effort '{reasoning_effort}'. Valid: {', '.join(sorted(valid_efforts))}."
            )

    validate_model_selection(runtime_adapter, model, reasoning_effort)


__all__ = [
    "AIPreferences",
    "build_ai_preferences_payload",
    "resolve_ai_preferences",
    "resolve_untagged_followup_mode",
    "validate_ai_preferences",
]
