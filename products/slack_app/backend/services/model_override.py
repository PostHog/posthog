"""One-off model choices expressed in the mention itself ("use fable for this one").

The Slack app already resolves a `(runtime_adapter, model, reasoning_effort)` triple
from the Home tab's personal and workspace rows (`slack_settings`). This module adds
the layer above it: a per-task override read out of the mention text.

Two rules keep the override honest. First, the catalogue is the same one the Home tab
picker renders — the live LLM-gateway model list intersected with the runtime adapters
the tasks product knows how to drive — so an override can never select something the
picker itself would refuse. Second, only the model id is ever taken from the
classifier: `runtime_adapter` is derived from the matched catalogue entry, and an
effort the chosen model doesn't support is dropped rather than passed through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache

from products.slack_app.backend.services.slack_settings import AIPreferences

# Substrings that survive the id split but read as ordinary English, so they would
# make the pre-filter fire on unrelated mentions.
_TOKEN_STOPLIST = frozenset({"ai", "cf", "com", "org"})

# Words that signal a reasoning-effort ask without naming a model. The bare effort
# values ("high", "max") are deliberately absent — they collide with everyday Slack
# English ("high priority", "max from support"), and a missed override just means the
# resolved preferences apply, which is the status quo.
_EFFORT_TERMS = frozenset({"effort", "reasoning", "thinking", "ultracode"})


@dataclass(frozen=True)
class ModelChoice:
    """One selectable model, flattened out of the Home tab's picker tree."""

    runtime_adapter: str
    model: str
    label: str
    supported_efforts: tuple[str, ...]


def available_model_choices() -> tuple[ModelChoice, ...]:
    """Every model a Slack-triggered run may use.

    Empty when the gateway is unreachable — callers must treat that as "no override
    possible" rather than falling back to a hardcoded list, so a gateway outage can't
    route a run to a model the gateway would reject anyway.
    """
    from products.slack_app.backend.services.slack_app_home import get_picker_choices

    return tuple(
        ModelChoice(
            runtime_adapter=adapter.value,
            model=model.value,
            label=model.label,
            supported_efforts=tuple(effort.value for effort in model.supported_efforts),
        )
        for adapter in get_picker_choices()
        for model in adapter.models
    )


def find_model_choice(model: str | None) -> ModelChoice | None:
    """Look a model id up in the live catalogue, case-insensitively."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((c for c in available_model_choices() if c.model.lower() == normalized), None)


def apply_model_override(
    base: AIPreferences,
    requested_model: str | None,
    requested_effort: str | None,
) -> AIPreferences:
    """Merge a requested model and/or effort onto the preferences a run would
    otherwise use, returning `base` untouched when nothing valid was asked for.

    A model change swaps the whole triple — the same rule `resolve_ai_preferences`
    applies between the user and workspace rows, so an effort saved against a
    previous model can't silently ride along onto a new one. An explicitly requested
    effort then applies on top, and is dropped if the resulting model doesn't
    support it.
    """
    resolved = base
    choice = find_model_choice(requested_model)
    if choice is not None:
        resolved = AIPreferences(runtime_adapter=choice.runtime_adapter, model=choice.model)

    if requested_effort:
        resolved = replace(resolved, reasoning_effort=requested_effort.strip().lower())

    if resolved.reasoning_effort:
        supported = find_model_choice(resolved.model)
        if supported is None or resolved.reasoning_effort not in supported.supported_efforts:
            resolved = replace(resolved, reasoning_effort=None)

    return resolved


def mentions_model_choice(text: str) -> bool:
    """Whether `text` is worth sending to the model classifier at all.

    A cheap word-boundary scan over the catalogue's own vocabulary, so the common
    mention never pays for an LLM call. Recall is deliberately imperfect: a request
    phrased without naming a model or the word "effort" ("use the smart one") is
    missed, and the run proceeds on the resolved preferences.
    """
    pattern = _candidate_pattern(tuple(sorted(_candidate_terms())))
    return bool(pattern and pattern.search(text.lower()))


def describe_preferences(preferences: AIPreferences) -> str:
    """Render a resolved model choice for a Slack thread reply, in the Home tab's phrasing."""
    from products.slack_app.backend.services.slack_app_home import REASONING_EFFORT_DISPLAY_NAMES, format_model_id

    label = format_model_id(preferences.model, owned_by="") if preferences.model else "—"
    if not preferences.reasoning_effort:
        return f"*{label}*"

    effort = REASONING_EFFORT_DISPLAY_NAMES.get(preferences.reasoning_effort, preferences.reasoning_effort)
    return f"*{label}* · Reasoning: *{effort}*"


def _candidate_terms() -> set[str]:
    """Vocabulary the pre-filter matches on: model ids, the words inside them, the
    runtime adapter names, and the effort terms."""
    terms = set(_EFFORT_TERMS)
    for choice in available_model_choices():
        terms.add(choice.model.lower())
        terms.add(choice.runtime_adapter.lower())
        terms.update(
            word
            for word in re.split(r"[^a-z0-9]+", choice.model.lower())
            if word.isalpha() and len(word) >= 3 and word not in _TOKEN_STOPLIST
        )
    return terms


@lru_cache(maxsize=8)
def _candidate_pattern(terms: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile the pre-filter regex. Cached on the term tuple so a catalogue change
    (or an empty catalogue during a gateway outage) rebuilds it, while repeated
    mentions reuse it."""
    if not terms:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![a-z0-9])")


__all__ = [
    "ModelChoice",
    "apply_model_override",
    "available_model_choices",
    "describe_preferences",
    "find_model_choice",
    "mentions_model_choice",
]
