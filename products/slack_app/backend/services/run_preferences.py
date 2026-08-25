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

A follow-up in a thread the agent is already working in resolves against a narrower
rule, in `resolve_live_run_override`: the runtime adapter is the harness process the
sandbox launched with and cannot change, so only the model and effort are still open.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class LiveRunModelChange:
    """What a run already in flight can take from a model request in a follow-up.

    `model` and `reasoning_effort` carry only what actually changes, so an ask that
    matches what the run is already on produces nothing to send. `refused_model` is the
    one ask that has to be answered out loud: a model belonging to the other runtime,
    which no live sandbox can be moved to.
    """

    model: str | None = None
    reasoning_effort: str | None = None
    refused_model: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.model is None and self.reasoning_effort is None and self.refused_model is None


_NO_CHANGE = LiveRunModelChange()


def resolve_live_run_override(
    override: ModelOverride | None,
    *,
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> LiveRunModelChange:
    """What a running agent can be switched to, given what a follow-up asked for.

    The three arguments describe the run as it stands. The runtime adapter is fixed for
    the life of a sandbox — the harness is a process that was started with one — so a
    model belonging to a different runtime is refused whole rather than half-applied,
    and its effort goes with it: "run this on sol at high" is one request, and honouring
    the effort alone would land it on a model the author didn't ask for.

    Beyond that the rules are the run resolver's: the effort is validated against the
    model the run will actually be on, and anything the catalogue doesn't offer is
    ignored, leaving the run where it was.
    """
    if override is None:
        return _NO_CHANGE

    # A run started before models were pinned carries neither; derive what we can, and
    # treat a run we can't place as unswitchable rather than guessing its harness.
    adapter = runtime_adapter or runtime_adapter_for(model)

    requested = find_model_choice(override.model, available_model_choices()) if override.model else None
    if override.model and requested is None:
        return _NO_CHANGE
    if requested is not None and requested.runtime_adapter != adapter:
        return LiveRunModelChange(refused_model=requested.model)

    target_model = requested.model if requested else model
    effort = filter_unsupported_effort(
        adapter, target_model, override.reasoning_effort.strip().lower() if override.reasoning_effort else None
    )
    return LiveRunModelChange(
        model=target_model if requested and requested.model != model else None,
        reasoning_effort=effort if effort and effort != reasoning_effort else None,
    )


def find_model_choice(model: str | None, choices: tuple[ModelChoice, ...]) -> ModelChoice | None:
    """Match a requested model id against the catalogue, case-insensitively."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((c for c in choices if c.model.lower() == normalized), None)


__all__ = [
    "SLACK_DEFAULT_MODEL",
    "LiveRunModelChange",
    "find_model_choice",
    "resolve_live_run_override",
    "resolve_run_preferences",
]
