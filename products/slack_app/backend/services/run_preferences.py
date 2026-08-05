"""Which model a Slack-triggered run actually uses.

One precedence chain, resolved in one place: a model named in the mention itself
("use fable for this one") beats the personal row, which beats the workspace row,
which falls back to the Slack default. `slack_settings` owns the personal-vs-workspace
half; this module owns the ends — the default underneath and the mention override on
top — so no caller has to assemble a triple by hand.

The triple is not three independent values. The runtime adapter follows from the
model, and which reasoning efforts exist depends on that pair, so every result is
built through `_coherent_preferences` rather than field by field. A model named in a
mention additionally has to be in the live catalogue (`model_catalogue`) — the same
set the App Home picker offers — so an override can never select something the picker
itself would refuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from products.slack_app.backend.services.model_catalogue import (
    ModelChoice,
    available_model_choices,
    filter_unsupported_effort,
    runtime_adapter_for,
)
from products.slack_app.backend.services.slack_settings import AIPreferences, resolve_ai_preferences

if TYPE_CHECKING:
    from posthog.models.integration import Integration

# What a Slack run uses when neither the user nor the workspace has pinned a model.
# Chosen here rather than left to the agent server so the App Home card and the run
# itself agree on what "unset" means.
SLACK_DEFAULT_MODEL = "claude-opus-5"


class ModelOverride(Protocol):
    """What a mention asked for. Structural so the Temporal payload satisfies it
    without this module importing anything from `posthog/temporal/`."""

    model: str | None
    reasoning_effort: str | None


def _coherent_preferences(
    model: str | None,
    reasoning_effort: str | None,
    *,
    fallback_runtime_adapter: str | None,
) -> AIPreferences:
    """Assemble the one self-consistent triple for a model.

    The runtime adapter is derived rather than passed in, and an effort the pair
    doesn't support is dropped. `fallback_runtime_adapter` covers a model the tasks
    catalogue no longer lists, where a stored adapter is the best information left.
    """
    runtime_adapter = runtime_adapter_for(model) or fallback_runtime_adapter
    effort = filter_unsupported_effort(
        runtime_adapter, model, reasoning_effort.strip().lower() if reasoning_effort else None
    )
    return AIPreferences(runtime_adapter=runtime_adapter, model=model, reasoning_effort=effort)


def resolve_run_preferences(
    integration: Integration,
    slack_user_id: str | None,
    *,
    override: ModelOverride | None = None,
) -> AIPreferences:
    """Resolve the full chain for one Slack-triggered run.

    A model named in the mention replaces the pair outright: an effort saved against
    the previous model must not ride along onto a different one. An effort named on its
    own applies to whichever model the run was already going to use. Either can be
    absent, and a request we can't honour — a model that isn't on offer, an effort the
    model doesn't support — leaves the run on its saved preferences.

    Note that `resolve_ai_preferences` yields nothing at all for a workspace that
    hasn't enabled `slack-app-home`, so there the chain is the Slack default plus
    whatever the mention asked for.
    """
    override_model = override.model if override else None
    override_effort = override.reasoning_effort if override else None

    if override_model:
        # Only a model named in the mention needs the catalogue, and the saved rows
        # can't influence the result, so neither is read on the other paths.
        choice = find_model_choice(override_model, available_model_choices())
        if choice is not None:
            return _coherent_preferences(choice.model, override_effort, fallback_runtime_adapter=choice.runtime_adapter)

    saved = resolve_ai_preferences(integration, slack_user_id)
    base = _coherent_preferences(
        saved.model or SLACK_DEFAULT_MODEL,
        saved.reasoning_effort,
        fallback_runtime_adapter=saved.runtime_adapter,
    )
    if not override_effort:
        return base

    # An effort this model can't do is dropped by `_coherent_preferences`; falling back
    # to `base` rather than to the stripped result means an impossible ask leaves the
    # run alone instead of quietly clearing the saved effort as well.
    requested = _coherent_preferences(base.model, override_effort, fallback_runtime_adapter=base.runtime_adapter)
    return requested if requested.reasoning_effort else base


def find_model_choice(model: str | None, choices: tuple[ModelChoice, ...]) -> ModelChoice | None:
    """Match a requested model id against the catalogue, case-insensitively."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((c for c in choices if c.model.lower() == normalized), None)


__all__ = [
    "SLACK_DEFAULT_MODEL",
    "find_model_choice",
    "resolve_run_preferences",
]
