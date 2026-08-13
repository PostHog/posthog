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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Importing this at runtime would execute `gateway_client`, pulling the Anthropic and OpenAI
    # SDKs onto slack_app's import path. It is only ever used as an annotation.
    from posthog.llm.gateway_client import Product


from products.tasks.backend.facade.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    ModelChoice,
    RuntimeGroup,
    available_model_choices as _available_model_choices,
    filter_unsupported_effort,
    format_model_id,
    group_by_runtime,
    label_for,
    runtime_adapter_for,
)

SLACK_APP_GATEWAY_PRODUCT: Product = "slack_app"


def available_model_choices() -> tuple[ModelChoice, ...]:
    """Every model a Slack-triggered run may use.

    Empty when the gateway is unreachable — callers must treat that as "no choice to
    offer" rather than falling back to a hardcoded list, so a gateway outage can't route
    a run to a model the gateway would reject anyway.
    """
    return _available_model_choices(SLACK_APP_GATEWAY_PRODUCT)


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
