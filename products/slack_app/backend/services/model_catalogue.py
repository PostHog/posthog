"""Which models a Slack-triggered run may use, and how to name them.

The catalogue is the live LLM-gateway model list for the `slack_app` product
(`llm_models`) intersected with the runtime adapters the tasks product knows how to
drive. Anything the gateway serves under a provider we can't route — bedrock, vertex —
is dropped rather than offered.

This is the single source for both consumers: the App Home picker renders it as a
Block Kit dropdown tree, and `model_override` matches a model named in a Slack mention
against it. Neither may hardcode a model list, and neither owns the display labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _runtime_adapter_by_provider() -> dict[str, str]:
    """Gateway `owned_by` → tasks runtime adapter.

    Inverted from the tasks product's own adapter → provider mapping rather than
    written out here, so the two can never disagree about which runtime serves a
    provider. Providers with no adapter (bedrock, vertex) are simply absent, which is
    what drops their models from the catalogue.
    """
    # Deferred because `facade.run_config` re-exports from a module that imports the
    # tasks ORM, mcp_store, and sandbox config at import time; keeping that off the
    # slack_app import path is the reason, and the App Home tests' `sys.modules` swap
    # depends on it staying that way.
    from products.tasks.backend.facade.run_config import (  # noqa: PLC0415
        RuntimeAdapter,
        get_provider_for_runtime_adapter,
    )

    by_provider = {}
    for adapter in RuntimeAdapter:
        provider = get_provider_for_runtime_adapter(adapter)
        if provider is not None:
            by_provider[provider.value] = adapter.value
    return by_provider


# Runtime + effort labels are UI strings with no tasks-product equivalent. Model
# display labels are computed from the model id on the fly via `format_model_id` so we
# never have to hand-maintain a model→label map.
RUNTIME_ADAPTER_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude (Anthropic)",
    "codex": "Codex (OpenAI)",
}

# Vendor initialisms that must not be title-cased into "Gpt".
_MODEL_ACRONYMS: dict[str, str] = {"gpt": "GPT", "glm": "GLM"}

REASONING_EFFORT_DISPLAY_NAMES: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Max",
    "ultracode": "Ultracode",
}


@dataclass(frozen=True)
class ModelChoice:
    """One model a Slack run may use, with the efforts that model supports."""

    runtime_adapter: str
    model: str
    label: str
    supported_efforts: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeGroup:
    """The models one runtime drives, under the name that runtime goes by."""

    runtime_adapter: str
    label: str
    choices: tuple[ModelChoice, ...]


def group_by_runtime(choices: tuple[ModelChoice, ...]) -> tuple[RuntimeGroup, ...]:
    """The catalogue as a runtime → models tree, in the order the catalogue gave.

    Both consumers present the catalogue this way and neither should decide for itself
    what a runtime is called: the App Home modal renders the tree as linked dropdowns,
    and the model-override classifier renders it as the list of ids it may pick from.
    The classifier needs the grouping to be visible rather than implied — people qualify
    a model with the runtime it belongs to ("codex sol"), and a flat list gives that word
    nothing to attach to, most sharply where a runtime name is also part of a model id
    (`gpt-5.3-codex`). A runtime with no models simply doesn't appear.
    """
    by_adapter: dict[str, list[ModelChoice]] = {}
    for choice in choices:
        by_adapter.setdefault(choice.runtime_adapter, []).append(choice)
    return tuple(
        RuntimeGroup(
            runtime_adapter=adapter,
            label=label_for(adapter, RUNTIME_ADAPTER_DISPLAY_NAMES),
            choices=tuple(grouped),
        )
        for adapter, grouped in by_adapter.items()
    )


def available_model_choices() -> tuple[ModelChoice, ...]:
    """Every model a Slack-triggered run may use.

    Empty when the gateway is unreachable — callers must treat that as "no choice to
    offer" rather than falling back to a hardcoded list, so a gateway outage can't
    route a run to a model the gateway would reject anyway.
    """
    from products.slack_app.backend.services.llm_models import list_slack_app_models  # noqa: PLC0415
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts  # noqa: PLC0415

    by_provider = _runtime_adapter_by_provider()
    choices = []
    for model in list_slack_app_models():
        runtime_adapter = by_provider.get(model.owned_by)
        if runtime_adapter is None:
            continue
        choices.append(
            ModelChoice(
                runtime_adapter=runtime_adapter,
                model=model.id,
                label=format_model_id(model.id),
                supported_efforts=tuple(e.value for e in get_supported_reasoning_efforts(runtime_adapter, model.id)),
            )
        )
    return tuple(choices)


def runtime_adapter_for(model: str | None) -> str | None:
    """Which runtime drives this model, per the tasks catalogue.

    The adapter is a property of the model rather than an independent choice, so
    deriving it is what keeps a `(runtime_adapter, model)` pair from ever disagreeing.
    `None` for a model the tasks product has no runtime for.
    """
    from products.tasks.backend.facade.run_config import get_runtime_adapter_for_model  # noqa: PLC0415

    adapter = get_runtime_adapter_for_model(model)
    return adapter.value if adapter else None


def filter_unsupported_effort(runtime_adapter: str | None, model: str | None, effort: str | None) -> str | None:
    """Drop an effort the given model doesn't support (e.g. a user saved `high` on a
    thinking model and then picked a non-thinking one).

    The single answer to "is this effort legal for this pair" — the stored-row resolver
    in `slack_settings` and the run resolver in `run_preferences` both route through it.
    """
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts  # noqa: PLC0415

    if not effort:
        return None
    return effort if effort in {e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)} else None


def format_model_id(model_id: str) -> str:
    """Turn a gateway model id into a display name: `Claude Opus 4.8`, `GPT-5.6 Sol`.

    Every family goes through the same rules — strip the provider prefix, glue a
    version onto a leading acronym, title-case the rest — so a new model is named
    without anyone touching a lookup table.
    """
    clean = model_id
    for provider in _runtime_adapter_by_provider():
        if clean.startswith(f"{provider}/"):
            clean = clean[len(provider) + 1 :]
            break

    # Collapse `4-8` into `4.8` so version components survive the dash split.
    words = re.split(r"[-_]", re.sub(r"(\d)-(\d)", r"\1.\2", clean))
    acronym = _MODEL_ACRONYMS.get(words[0].lower())
    if acronym is None:
        return " ".join(_titled(word) for word in words)
    # `gpt` + `5.6` reads as `GPT-5.6`, the way the vendor writes it, with any
    # remaining qualifier ("sol", "codex", "mini") as its own word.
    head = f"{acronym}-{words[1]}" if len(words) > 1 else acronym
    return " ".join([head, *(_titled(word) for word in words[2:])])


def _titled(word: str) -> str:
    """Capitalise a name part, leaving bare version numbers alone."""
    if re.fullmatch(r"[0-9.]+", word):
        return word
    return word[:1].upper() + word[1:].lower()


def label_for(value: str | None, mapping: dict[str, str]) -> str:
    """Display name for a stored value, falling back to the value itself."""
    if not value:
        return "—"
    return mapping.get(value, value)


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
