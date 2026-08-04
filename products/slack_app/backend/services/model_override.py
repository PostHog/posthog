"""One-off model choices expressed in the mention itself ("use fable for this one").

The Slack app already resolves a `(runtime_adapter, model, reasoning_effort)` triple
from the Home tab's personal and workspace rows (`slack_settings`). This module adds
the layer above it: a per-task override read out of the mention text.

Two rules keep the override honest. First, a model is only accepted if it is in the
live catalogue (`model_catalogue`) — the same set the Home tab picker offers — so an
override can never select something the picker itself would refuse. Second, only the
model id is ever taken from the classifier: `runtime_adapter` is derived from the
matched catalogue entry, and an effort the chosen model doesn't support is dropped
rather than passed through.
"""

from __future__ import annotations

import re

from products.slack_app.backend.services.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    ModelChoice,
    available_model_choices,
    format_model_id,
    label_for,
    supported_efforts_for,
)
from products.slack_app.backend.services.slack_settings import AIPreferences

# Words that survive the model-id split but read as ordinary English, so they would
# make the pre-filter fire on unrelated mentions.
_TOKEN_STOPLIST = frozenset({"com", "org"})

# Words that signal a reasoning-effort ask without naming a model. The bare effort
# values ("high", "max") are deliberately absent — they collide with everyday Slack
# English ("high priority", "max from support"), and a missed override just means the
# resolved preferences apply, which is the status quo.
_EFFORT_TERMS = frozenset({"effort", "reasoning", "thinking", "ultracode"})


def find_model_choice(model: str | None, choices: tuple[ModelChoice, ...]) -> ModelChoice | None:
    """Match a requested model id against the catalogue, case-insensitively."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((c for c in choices if c.model.lower() == normalized), None)


def apply_model_override(
    base: AIPreferences,
    requested_model: str | None,
    requested_effort: str | None,
) -> AIPreferences:
    """Merge a requested model and/or effort onto the preferences a run would
    otherwise use, returning `base` untouched when nothing valid was asked for.

    A model change swaps the whole triple — the same rule `resolve_ai_preferences`
    applies between the user and workspace rows, so an effort saved against a previous
    model can't silently ride along onto a new one. An explicitly requested effort then
    applies on top, and is dropped if the resulting model doesn't support it.
    """
    runtime_adapter: str | None
    model: str | None
    effort: str | None

    choice = find_model_choice(requested_model, available_model_choices())
    if choice is not None:
        runtime_adapter, model, effort = choice.runtime_adapter, choice.model, None
    else:
        runtime_adapter, model, effort = base.runtime_adapter, base.model, base.reasoning_effort

    if requested_effort:
        effort = requested_effort.strip().lower()
    if effort and effort not in supported_efforts_for(runtime_adapter, model):
        effort = None

    return AIPreferences(runtime_adapter=runtime_adapter, model=model, reasoning_effort=effort)


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


def describe_preferences(preferences: AIPreferences) -> str:
    """Render a resolved model choice for Slack, in one phrasing shared by the App Home
    card and the thread notice a mention override posts."""
    label = format_model_id(preferences.model, owned_by="") if preferences.model else "—"
    if not preferences.reasoning_effort:
        return f"*{label}*"
    return f"*{label}* · Reasoning: *{label_for(preferences.reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}*"


__all__ = [
    "apply_model_override",
    "describe_preferences",
    "find_model_choice",
    "mentions_model_choice",
]
