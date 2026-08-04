"""What model a Slack-triggered run actually uses, and how to say it.

One precedence chain, resolved in one place: a model named in the mention itself
("use fable for this one") beats the personal row, which beats the workspace row,
which falls back to the Slack default. `slack_settings` owns the personal-vs-workspace
half; this module owns the ends — the default underneath and the mention override on
top — so no caller has to assemble a triple by hand.

The triple is not three independent values. The runtime adapter follows from the
model, and which reasoning efforts exist depends on that pair, so every result is
built through `coherent_preferences` rather than field by field. A model named in a
mention additionally has to be in the live catalogue (`model_catalogue`) — the same
set the App Home picker offers — so an override can never select something the picker
itself would refuse.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from products.slack_app.backend.services.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    ModelChoice,
    available_model_choices,
    format_model_id,
    label_for,
    runtime_adapter_for,
)
from products.slack_app.backend.services.slack_settings import AIPreferences, resolve_ai_preferences

if TYPE_CHECKING:
    from posthog.models.integration import Integration

# What a Slack run uses when neither the user nor the workspace has pinned a model.
# Chosen here rather than left to the agent server so the App Home card and the run
# itself agree on what "unset" means.
SLACK_DEFAULT_MODEL = "claude-opus-5"

# Words that survive the model-id split but read as ordinary English, so they would
# make the pre-filter fire on unrelated mentions.
_TOKEN_STOPLIST = frozenset({"com", "org"})

# Words that signal a reasoning-effort ask without naming a model. The bare effort
# values ("high", "max") are deliberately absent — they collide with everyday Slack
# English ("high priority", "max from support"), and a missed override just means the
# resolved preferences apply, which is the status quo.
_EFFORT_TERMS = frozenset({"effort", "reasoning", "thinking", "ultracode"})


def coherent_preferences(
    model: str | None,
    reasoning_effort: str | None,
    *,
    fallback_runtime_adapter: str | None = None,
) -> AIPreferences:
    """Assemble the one self-consistent triple for a model.

    The runtime adapter is derived rather than passed in, and an effort the pair
    doesn't support is dropped. `fallback_runtime_adapter` covers a model the tasks
    catalogue no longer lists, where a stored adapter is the best information left.
    """
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    runtime_adapter = runtime_adapter_for(model) or fallback_runtime_adapter
    effort = reasoning_effort.strip().lower() if reasoning_effort else None
    if effort and effort not in {e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)}:
        effort = None
    return AIPreferences(runtime_adapter=runtime_adapter, model=model, reasoning_effort=effort)


def resolve_run_preferences(
    integration: Integration,
    slack_user_id: str | None,
    *,
    override_model: str | None = None,
    override_effort: str | None = None,
) -> AIPreferences:
    """Resolve the full chain for one Slack-triggered run.

    A model named in the mention replaces the pair outright: an effort saved against
    the previous model must not ride along onto a different one. An effort named on its
    own applies to whichever model the run was already going to use. Either can be
    absent, and a request we can't honour — a model that isn't on offer, an effort the
    model doesn't support — leaves the run on its saved preferences.
    """
    saved = resolve_ai_preferences(integration, slack_user_id)
    base = coherent_preferences(
        saved.model or SLACK_DEFAULT_MODEL,
        saved.reasoning_effort,
        fallback_runtime_adapter=saved.runtime_adapter,
    )

    choice = find_model_choice(override_model, available_model_choices())
    if choice is not None:
        return coherent_preferences(choice.model, override_effort, fallback_runtime_adapter=choice.runtime_adapter)
    if override_effort:
        requested = coherent_preferences(base.model, override_effort, fallback_runtime_adapter=base.runtime_adapter)
        # An effort this model can't do is dropped by `coherent_preferences`; falling
        # back to `base` rather than to the stripped result means an impossible ask
        # leaves the run alone instead of quietly clearing a saved effort as well.
        return requested if requested.reasoning_effort else base
    return base


def find_model_choice(model: str | None, choices: tuple[ModelChoice, ...]) -> ModelChoice | None:
    """Match a requested model id against the catalogue, case-insensitively."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((c for c in choices if c.model.lower() == normalized), None)


def mentions_model_choice(text: str, choices: tuple[ModelChoice, ...]) -> bool:
    """Whether `text` is worth sending to the model classifier at all.

    A cheap word-boundary scan over the catalogue's own vocabulary — model ids, the
    words inside them, the runtime adapter names, and the effort terms — so the common
    mention never pays for an LLM call. Recall is deliberately imperfect: a request
    phrased without naming a model or the word "effort" ("use the smart one") is
    missed, and the run proceeds on the resolved preferences.
    """
    terms = set(_EFFORT_TERMS)
    for choice in choices:
        terms.add(choice.model.lower())
        terms.add(choice.runtime_adapter.lower())
        terms.update(
            word
            for word in re.split(r"[^a-z0-9]+", choice.model.lower())
            if word.isalpha() and len(word) >= 3 and word not in _TOKEN_STOPLIST
        )

    pattern = r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in sorted(terms)) + r")(?![a-z0-9])"
    return bool(re.search(pattern, text.lower()))


def describe_run_model(model: str | None, reasoning_effort: str | None) -> str:
    """Render the model a run is on, in one phrasing shared by the App Home card and
    the progress message in the Slack thread."""
    label = format_model_id(model, owned_by="") if model else "—"
    if not reasoning_effort:
        return f"*{label}*"
    return f"*{label}* · Reasoning: *{label_for(reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}*"


__all__ = [
    "SLACK_DEFAULT_MODEL",
    "coherent_preferences",
    "describe_run_model",
    "find_model_choice",
    "mentions_model_choice",
    "resolve_run_preferences",
]
