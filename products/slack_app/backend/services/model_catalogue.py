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

# Gateway `owned_by` → tasks RuntimeAdapter value. Other providers are dropped.
_PROVIDER_TO_RUNTIME_ADAPTER: dict[str, str] = {
    "anthropic": "claude",
    "openai": "codex",
}

_PROVIDER_PREFIXES = ("anthropic/", "openai/")

# Runtime + effort labels are UI strings with no tasks-product equivalent. Model
# display labels are computed from the model id on the fly via `format_model_id` so we
# never have to hand-maintain a model→label map.
RUNTIME_ADAPTER_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude (Anthropic)",
    "codex": "Codex (OpenAI)",
}

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


def available_model_choices() -> tuple[ModelChoice, ...]:
    """Every model a Slack-triggered run may use.

    Empty when the gateway is unreachable — callers must treat that as "no choice to
    offer" rather than falling back to a hardcoded list, so a gateway outage can't
    route a run to a model the gateway would reject anyway.
    """
    from products.slack_app.backend.services.llm_models import list_slack_app_models
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    choices = []
    for model in list_slack_app_models():
        runtime_adapter = _PROVIDER_TO_RUNTIME_ADAPTER.get(model.owned_by)
        if runtime_adapter is None:
            continue
        choices.append(
            ModelChoice(
                runtime_adapter=runtime_adapter,
                model=model.id,
                label=format_model_id(model.id, owned_by=model.owned_by),
                supported_efforts=tuple(e.value for e in get_supported_reasoning_efforts(runtime_adapter, model.id)),
            )
        )
    return tuple(choices)


def supported_efforts_for(runtime_adapter: str | None, model: str | None) -> frozenset[str]:
    """Efforts the tasks product will accept for this pair.

    Read straight from the tasks catalogue rather than from a `ModelChoice`, so the
    answer is still right for a model the gateway has since stopped listing.
    """
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    return frozenset(e.value for e in get_supported_reasoning_efforts(runtime_adapter, model))


def provider_for_runtime_adapter(runtime_adapter: str | None) -> str:
    """The gateway `owned_by` a runtime adapter implies.

    Derived from the forward mapping rather than restated, so the two can't drift when
    an adapter is added.
    """
    for provider, adapter in _PROVIDER_TO_RUNTIME_ADAPTER.items():
        if adapter == runtime_adapter:
            return provider
    return "anthropic"


def format_model_id(model_id: str, *, owned_by: str) -> str:
    """OpenAI ids stay lowercase; Claude ids become `Claude Opus 4.8` etc."""
    clean = model_id
    for prefix in _PROVIDER_PREFIXES:
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            break
    if owned_by == "openai":
        return clean.lower()

    # Collapse `4-8` into `4.8` so version components survive the dash split.
    clean = re.sub(r"(\d)-(\d)", r"\1.\2", clean)
    return " ".join(
        word if re.fullmatch(r"[0-9.]+", word) else word[:1].upper() + word[1:].lower()
        for word in re.split(r"[-_]", clean)
    )


def label_for(value: str | None, mapping: dict[str, str]) -> str:
    """Display name for a stored value, falling back to the value itself."""
    if not value:
        return "—"
    return mapping.get(value, value)


__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "ModelChoice",
    "available_model_choices",
    "format_model_id",
    "label_for",
    "provider_for_runtime_adapter",
    "supported_efforts_for",
]
