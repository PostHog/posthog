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
    # The tasks facade imports the tasks ORM, so it is loaded on use rather than at
    # module scope — that keeps it off the slack_app import path, and lets the
    # product's tests swap the facade in `sys.modules`.
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
                label=format_model_id(model.id, owned_by=model.owned_by),
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
    from products.tasks.backend.facade.run_config import RuntimeAdapter, get_models_for_runtime_adapter  # noqa: PLC0415

    if not model:
        return None
    normalized = model.strip().lower()
    for adapter in RuntimeAdapter:
        if any(known.lower() == normalized for known in get_models_for_runtime_adapter(adapter)):
            return adapter.value
    return None


def provider_for_model(model: str | None) -> str:
    """Gateway provider that serves this model, or `""` when we can't tell.

    Lets a caller holding only a model id (a stored preference, a run's state) format
    it the way the picker does, instead of guessing the provider or dropping the
    casing rules that depend on it.
    """
    adapter = runtime_adapter_for(model)
    if adapter is None:
        return ""
    return next((provider for provider, value in _runtime_adapter_by_provider().items() if value == adapter), "")


def provider_for_runtime_adapter(runtime_adapter: str | None) -> str:
    """The gateway `owned_by` a runtime adapter implies.

    Read back out of the same derived mapping the catalogue is built from, so an adapter
    added to the tasks product is answered here without touching this module.
    """
    for provider, adapter in _runtime_adapter_by_provider().items():
        if adapter == runtime_adapter:
            return provider
    return "anthropic"


def format_model_id(model_id: str, *, owned_by: str) -> str:
    """OpenAI ids stay lowercase; Claude ids become `Claude Opus 4.8` etc."""
    clean = model_id
    for provider in _runtime_adapter_by_provider():
        if clean.startswith(f"{provider}/"):
            clean = clean[len(provider) + 1 :]
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
    "provider_for_model",
    "runtime_adapter_for",
]
