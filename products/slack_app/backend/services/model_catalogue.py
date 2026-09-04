"""Which models a Slack-triggered run may use, and how to name them.

The catalogue itself lives in the tasks product — one definition every surface derives
from, so the App Home picker, the web composer, and `model_override` can never disagree
about what exists. This module binds it to the `slack_app` gateway product and adds the
one piece of presentation Slack owns: mrkdwn phrasing.

This is the single source for both Slack consumers: the App Home picker renders it as a
Block Kit dropdown tree, and `model_override` matches a model named in a Slack mention
against it. Neither may hardcode a model list.
"""

from __future__ import annotations

from products.tasks.backend.facade.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    ModelChoice,
    RuntimeGroup,
    catalog_model_choices,
    filter_unsupported_effort,
    format_model_id,
    group_by_runtime,
    label_for,
    runtime_adapter_for,
)


def available_model_choices() -> tuple[ModelChoice, ...]:
    """Every model a Slack-triggered run may use.

    Read from the catalog rather than the gateway. Slack asks only what the catalog
    answers — whether a mention names a real model, which runtime drives it, and what
    efforts it takes — so the list no longer depends on a network call that can come
    back empty and leave a mention with nothing to match against.
    """
    return catalog_model_choices()


def describe_run_model(model: str | None, reasoning_effort: str | None) -> str:
    """Render the model a run is on, in one phrasing shared by the App Home card and
    the progress message in the Slack thread."""
    label = format_model_id(model) if model else "—"
    if not reasoning_effort:
        return f"*{label}*"
    return f"*{label}* · Reasoning: *{label_for(reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}*"


__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "describe_run_model",
    "filter_unsupported_effort",
    "format_model_id",
    "group_by_runtime",
    "label_for",
    "runtime_adapter_for",
]
