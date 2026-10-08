"""The options the automatic model choice picks from for a new Slack task.

The options are the capability ladder plus the stored defaults, and not every model and
effort pair, because a System One choice question takes at most 16 options on the gateway.
The decision model reads only the option text and scores each option against its own text,
so the model and effort notes sit in each option and not once in the instructions.
"""

from __future__ import annotations

from dataclasses import dataclass

from posthog.llm.system_one import JsonValue

from products.slack_app.backend.services.model_catalogue import (
    CAPABILITY_LADDER_BY_RUNTIME_ADAPTER,
    COST_BASELINE_MODEL,
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    ModelChoice,
    available_model_choices,
    display_name_for_model,
    filter_unsupported_effort,
    label_for,
    offered_model_choices,
)
from products.slack_app.backend.services.run_preferences import SLACK_DEFAULT_MODEL, find_model_choice

PERSONAL_DEFAULT_NOTE = "This is the user's personal default."
PROJECT_DEFAULT_NOTE = "This is the project default."
SLACK_DEFAULT_NOTE = "This is the default for Slack tasks in this project."

_LUNA_NOTE = (
    "A light and very cheap model. Good for short answers, lookups, summaries and very small edits. "
    "Not good for changes across many files."
)
_SOL_NOTE = (
    "A general coding model. Good for most code changes and debugging. "
    "It becomes stronger as the reasoning effort goes up."
)

# Keyed by id prefix, so a new version of a family gets its note without an edit. A model on
# the capability ladder must match one, or the router picks it blind.
_MODEL_NOTES: dict[str, str] = {
    "claude-sonnet": (
        "A balanced model. Good for most code changes, bug fixes with a clear cause, and PostHog data questions."
    ),
    "claude-opus": (
        "A strong model for deep work. Good for large or unclear code changes, hard bugs, "
        "and research across many files."
    ),
    "claude-fable": (
        "The most capable Claude model. Good only for the hardest problems, for example a design change "
        "across many systems or a subtle data or concurrency bug."
    ),
    "gpt-6-astra": "The most capable OpenAI model. Good only for the hardest problems.",
    "gpt-6-luna": _LUNA_NOTE,
    "gpt-5.6-luna": _LUNA_NOTE,
    "gpt-5.6-terra": "A mid-size model. Good for normal code changes with a clear goal.",
    "gpt-6-sol": _SOL_NOTE,
    "gpt-6.1-sol": _SOL_NOTE,
    "gpt-5.6-sol": _SOL_NOTE,
}

_EFFORT_NOTES: dict[str, str] = {
    "low": "Thinks briefly. Fastest and cheapest. Good when the answer is direct.",
    "medium": "Thinks a moderate amount. Good for normal tasks with a clear goal.",
    "high": "Thinks with care. Good for changes in several steps and for debugging.",
    "xhigh": "Thinks at length. Good for hard bugs and changes across many files.",
    "max": "Thinks as long as it needs. Slowest. Good only for the hardest problems.",
    "ultracode": "The longest and most thorough coding mode. Good only for very large code changes.",
}

# User text stays in `state`. The instructions only name its fields, so the request cannot
# become an instruction.
MODEL_ROUTER_INSTRUCTIONS: dict[str, JsonValue] = {
    "task": (
        "Pick the model and the reasoning effort for a new task that the PostHog agent runs. "
        "The agent can change code in a repository, open pull requests, query PostHog data and change PostHog settings."
    ),
    "input": (
        "state.request is the Slack message that starts the task. "
        "state.repository is the code repository the task works in, or null when the task works without code."
    ),
    "goal": (
        "Pick the cheapest option that will most likely finish the task correctly on the first try. "
        "A failed run costs more than a smarter option, because the user must wait and ask again."
    ),
    "cost": (
        "Each option shows its cost per token. A higher reasoning effort uses more tokens, "
        "so the run takes longer and costs more."
    ),
    "pick_a_smarter_option_when": [
        "The request asks for a new feature, a refactor, or a change across many files.",
        "The request asks to find the cause of a bug, a flaky test, a crash or a performance problem.",
        "The request is unclear, and the agent must research the code or the data to know what to do.",
        "The request asks for a design, a plan or a careful review.",
    ],
    "pick_a_faster_option_when": [
        "The request asks a direct question with a short answer, for example a count, a definition or a link.",
        "The request asks for one PostHog query, one insight or a summary of data.",
        "The request asks for a small, clear edit, for example a typo, a copy change or a version bump.",
        "state.repository is null and the request does not ask for code.",
    ],
    "rules": [
        "Judge the work that the request needs, not the length of the message. A short message can ask for hard work.",
        "Stay on the runtime of the default option. Change the runtime only when the other runtime has "
        "a clearly better option for this request.",
        "Pick the top step of a scale only when the request is clearly one of the hardest tasks.",
        "When two options fit equally well, pick the user's personal default, then the project default, "
        "then the default for Slack tasks.",
    ],
}


@dataclass(frozen=True)
class ModelRouterOption:
    model: str
    reasoning_effort: str | None
    description: str

    @property
    def key(self) -> str:
        return f"{self.model} @ {self.reasoning_effort}" if self.reasoning_effort else self.model


@dataclass(frozen=True)
class _Candidate:
    choice: ModelChoice
    reasoning_effort: str | None
    ladder_note: str | None = None
    notes: tuple[str, ...] = ()


def _stored_default(
    preferences: dict[str, str], choices: tuple[ModelChoice, ...]
) -> tuple[ModelChoice, str | None] | None:
    """`None` when no Slack run can use the preference, because Slack runs only on ACP."""
    if preferences.get("runtime") not in (None, "", "acp"):
        return None
    choice = find_model_choice(preferences.get("model"), choices)
    if choice is None:
        return None
    return choice, filter_unsupported_effort(choice.runtime_adapter, choice.model, preferences.get("reasoning_effort"))


def _model_note(model: str) -> str | None:
    return next((note for prefix, note in _MODEL_NOTES.items() if model.startswith(prefix)), None)


def _describe(candidate: _Candidate) -> str:
    choice = candidate.choice
    effort = candidate.reasoning_effort
    parts = [
        display_name_for_model(choice.model)
        + (f" at {label_for(effort, REASONING_EFFORT_DISPLAY_NAMES).lower()} reasoning effort." if effort else "."),
        f"Runtime: {label_for(choice.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)}.",
    ]
    if model_note := _model_note(choice.model):
        parts.append(f"Model: {model_note}")
    if effort and (effort_note := _EFFORT_NOTES.get(effort)):
        parts.append(f"Effort: {effort_note}")
    if choice.cost_multiplier:
        parts.append(
            f"Cost per token compared to {display_name_for_model(COST_BASELINE_MODEL)}: {choice.cost_multiplier}."
        )
    if candidate.ladder_note:
        parts.append(candidate.ladder_note)
    parts.extend(candidate.notes)
    return " ".join(parts)


def model_router_options(
    *,
    team_id: int,
    user_id: int | None,
    distinct_id: str | None,
) -> tuple[ModelRouterOption, ...]:
    """Leaves out models the viewer may not use, so task creation never refuses the pick."""
    from products.tasks.backend.facade import (  # noqa: PLC0415 — keep tasks deps off the slack_app import path
        ai_run_defaults,
    )
    from products.tasks.backend.facade.run_config import (  # noqa: PLC0415 — keep tasks deps off the slack_app import path
        get_model_access_error,
    )

    catalog = available_model_choices()
    offered = offered_model_choices()

    candidates: dict[tuple[str, str | None], _Candidate] = {}

    def add(
        choice: ModelChoice, effort: str | None, *, ladder_note: str | None = None, note: str | None = None
    ) -> None:
        key = (choice.model, effort)
        existing = candidates.get(key) or _Candidate(choice=choice, reasoning_effort=effort)
        candidates[key] = _Candidate(
            choice=choice,
            reasoning_effort=effort,
            ladder_note=existing.ladder_note or ladder_note,
            notes=(*existing.notes, note) if note else existing.notes,
        )

    # A stored default may name a retired model. The person chose it, so it stays an option.
    if user_id is not None:
        personal = _stored_default(ai_run_defaults.get_user_ai_run_preferences(team_id, user_id), catalog)
        if personal is not None:
            add(*personal, note=PERSONAL_DEFAULT_NOTE)
    project = _stored_default(ai_run_defaults.get_team_ai_run_preferences(team_id), catalog)
    if project is not None:
        add(*project, note=PROJECT_DEFAULT_NOTE)
    # Without a stored default the run falls to Slack's own, and the tie-break needs to see it.
    if not candidates and (slack_default := find_model_choice(SLACK_DEFAULT_MODEL, catalog)) is not None:
        add(slack_default, None, note=SLACK_DEFAULT_NOTE)

    for runtime_adapter, ladder in CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.items():
        runtime_label = label_for(runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)
        for index, notch in enumerate(ladder, start=1):
            choice = find_model_choice(notch.model, offered)
            if choice is None:
                continue
            effort = filter_unsupported_effort(choice.runtime_adapter, choice.model, notch.effort)
            add(
                choice,
                effort,
                ladder_note=f"Step {index} of {len(ladder)} on the {runtime_label} scale from fastest to smartest.",
            )

    # The check can be a network call per model, and the ladder repeats models across efforts.
    allowed = {
        model
        for model in {c.choice.model for c in candidates.values()}
        if get_model_access_error(model, distinct_id=distinct_id) is None
    }
    return tuple(
        ModelRouterOption(model=c.choice.model, reasoning_effort=c.reasoning_effort, description=_describe(c))
        for c in candidates.values()
        if c.choice.model in allowed
    )


__all__ = [
    "MODEL_ROUTER_INSTRUCTIONS",
    "ModelRouterOption",
    "model_router_options",
]
