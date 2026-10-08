"""The options the automatic model choice picks from for a new Slack task.

Each option is one model at one reasoning effort. The catalog's capability ladder supplies
the spine: a curated Faster → Smarter list per runtime, where each rung is worth its extra
cost over the one below. Every pair of model and effort the catalog allows would not fit,
because a System One choice question takes at most 16 options on the gateway. The viewer's
personal default and the project default join the ladder, so the router can always keep
the run where it would go without it.

Options carry a plain description because the decision model reads only that text. It
knows nothing about a model id beyond what the description says.
"""

from __future__ import annotations

from dataclasses import dataclass

from products.slack_app.backend.services.model_catalogue import (
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

PERSONAL_DEFAULT_NOTE = "This is the user's personal default."
PROJECT_DEFAULT_NOTE = "This is the project default."


@dataclass(frozen=True)
class ModelRouterOption:
    model: str
    reasoning_effort: str | None
    description: str

    @property
    def key(self) -> str:
        """The option name the decision model answers with. Unique per (model, effort)."""
        return f"{self.model} @ {self.reasoning_effort}" if self.reasoning_effort else self.model


@dataclass(frozen=True)
class _Candidate:
    choice: ModelChoice
    reasoning_effort: str | None
    ladder_note: str | None = None
    notes: tuple[str, ...] = ()


def _find(model: str | None, choices: tuple[ModelChoice, ...]) -> ModelChoice | None:
    return next((c for c in choices if c.model == model), None) if model else None


def _stored_default(
    preferences: dict[str, str], choices: tuple[ModelChoice, ...]
) -> tuple[ModelChoice, str | None] | None:
    """A stored preference as a (model, effort) pair, or `None` when no Slack run can use it.

    A Pi preference has no runtime adapter, and Slack runs only on ACP.
    """
    if preferences.get("runtime") not in (None, "", "acp"):
        return None
    choice = _find(preferences.get("model"), choices)
    if choice is None:
        return None
    return choice, filter_unsupported_effort(choice.runtime_adapter, choice.model, preferences.get("reasoning_effort"))


def _describe(candidate: _Candidate) -> str:
    choice = candidate.choice
    parts = [
        display_name_for_model(choice.model)
        + (
            f" at {label_for(candidate.reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES).lower()} reasoning effort."
            if candidate.reasoning_effort
            else "."
        ),
        f"Runtime: {label_for(choice.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)}.",
    ]
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
    """The options for one new task, defaults first and then each runtime's ladder.

    An option drops out when the viewer may not use its model, so the router can never
    pick a run that task creation would refuse.
    """
    from products.tasks.backend.facade import (  # noqa: PLC0415 — keep tasks deps off the slack_app import path
        ai_run_defaults,
    )
    from products.tasks.backend.facade.model_catalogue import (  # noqa: PLC0415 — keep tasks deps off the slack_app import path
        CAPABILITY_LADDER_BY_RUNTIME_ADAPTER,
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

    for runtime_adapter, ladder in CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.items():
        runtime_label = label_for(runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)
        for index, notch in enumerate(ladder, start=1):
            choice = _find(notch.model, offered)
            if choice is None:
                continue
            effort = filter_unsupported_effort(choice.runtime_adapter, choice.model, notch.effort)
            add(
                choice,
                effort,
                ladder_note=f"Step {index} of {len(ladder)} on the {runtime_label} scale from fastest to smartest.",
            )

    return tuple(
        ModelRouterOption(model=c.choice.model, reasoning_effort=c.reasoning_effort, description=_describe(c))
        for c in candidates.values()
        if get_model_access_error(c.choice.model, distinct_id=distinct_id) is None
    )


__all__ = [
    "ModelRouterOption",
    "model_router_options",
]
