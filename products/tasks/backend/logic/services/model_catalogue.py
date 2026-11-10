"""Which models a task run may use, and how to name them.

The catalogue is the static model catalog, narrowed to the models a gateway product's
token pin admits. It is read without a network call, so a picker render never waits on
the LLM gateway and a gateway outage never empties a picker.

Every surface that offers a model picker derives from here: the task composer in the
web app and PostHog Code (`posthog_code`), the Slack App Home picker and the
model-override classifier (`slack_app`). None of them may hardcode a model list, and
none of them owns the display labels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from products.tasks.backend import model_catalog
from products.tasks.backend.logic.services.gateway_model_pin import model_allowed_by_product_pin
from products.tasks.backend.model_catalog import COST_BASELINE_MODEL, display_name_for_model  # noqa: F401 — re-exported

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

# The gateway product a user-initiated task run authenticates as — the same one the
# sandbox agent uses, so the picker can only ever offer models the run itself may call.
TASK_RUN_GATEWAY_PRODUCT: Product = "posthog_code"

# A runtime's name is a UI string with no run-config equivalent, so it is written here. A
# model's comes from `display_name_for_model`, and an effort's from the catalog.
RUNTIME_ADAPTER_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude (Anthropic)",
    "codex": "Codex (OpenAI)",
}

REASONING_EFFORT_DISPLAY_NAMES: dict[str, str] = model_catalog.REASONING_EFFORT_LABELS


@dataclass(frozen=True)
class ModelChoice:
    """One model a run may use, with the efforts that model supports.

    `supported_efforts` is empty for a model with no effort control — that is a real
    answer, not missing metadata, so a picker should render the model with no effort
    dropdown rather than hiding it.

    `cost_multiplier` is what this model costs per token against the catalog's baseline,
    already rendered (`2.5×`, `≈0.55×`). `None` where the catalog quotes no rate, and a
    picker then offers the model with no cost beside it.
    """

    runtime_adapter: str
    model: str
    label: str
    supported_efforts: tuple[str, ...]
    cost_multiplier: str | None = None
    context_window: int = 0
    allowed: bool = True


@dataclass(frozen=True)
class RuntimeGroup:
    """The models one runtime drives, under the name that runtime goes by."""

    runtime_adapter: str
    label: str
    choices: tuple[ModelChoice, ...]


def group_by_runtime(choices: tuple[ModelChoice, ...]) -> tuple[RuntimeGroup, ...]:
    """The catalogue as a runtime → models tree, in the order the catalogue gave.

    Consumers present the catalogue this way and none should decide for itself what a
    runtime is called: the App Home modal renders the tree as linked dropdowns, and the
    model-override classifier renders it as the list of ids it may pick from. The
    classifier needs the grouping to be visible rather than implied — people qualify a
    model with the runtime it belongs to ("codex sol"), and a flat list gives that word
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


def available_model_choices(product: Product) -> tuple[ModelChoice, ...]:
    """Every model a picker may offer a run on the given gateway product."""
    return tuple(choice for choice in offered_model_choices() if model_allowed_by_product_pin(product, choice.model))


def runnable_model_choices(product: Product) -> tuple[ModelChoice, ...]:
    """Every model a run on the given gateway product may call, retired ones included."""
    return tuple(choice for choice in catalog_model_choices() if model_allowed_by_product_pin(product, choice.model))


def plan_model_choices(product: Product, plan_pin: str) -> tuple[ModelChoice, ...]:
    """The product's choices, each marked with whether the caller's plan pin admits it."""
    return tuple(
        replace(choice, allowed=model_allowed_by_product_pin(plan_pin, choice.model))
        for choice in available_model_choices(product)
    )


@lru_cache(maxsize=1)
def catalog_model_choices() -> tuple[ModelChoice, ...]:
    """Every model the catalog serves, without asking the gateway.

    The gateway answers one question the catalog cannot — which models it is serving
    right now — and a caller that only needs to recognise a model and read what it
    supports is asking the catalog's questions, not that one. Those callers take this
    and stay off the network.
    """
    return tuple(
        ModelChoice(
            runtime_adapter=entry.runtime_adapter,
            model=entry.id,
            label=model_catalog.display_name_for_model(entry.id),
            supported_efforts=entry.reasoning_efforts,
            cost_multiplier=model_catalog.cost_multiplier_label(entry.id),
            context_window=entry.context_window,
        )
        for entry in model_catalog.MODELS
    )


@lru_cache(maxsize=1)
def offered_model_choices() -> tuple[ModelChoice, ...]:
    """The models a picker may offer: every catalog model except the retired ones.

    A caller that recognises a model a person named, rather than asking them to choose one,
    wants ``catalog_model_choices`` instead. A retired model still runs and still reads its
    name and cost from the catalog.
    """
    return tuple(choice for choice in catalog_model_choices() if model_catalog.is_offered_model(choice.model))


def runtime_adapter_for(model: str | None) -> str | None:
    """Which runtime drives this model, per the static run-config map.

    The adapter is a property of the model rather than an independent choice, so
    deriving it is what keeps a `(runtime_adapter, model)` pair from ever disagreeing.
    `None` for a model this product has no runtime for.
    """
    # Deferred because `temporal.process_task.utils` pulls the tasks ORM, mcp_store, and
    # sandbox config at import time; keeping that off the import path of every catalogue
    # consumer is the reason, and the App Home tests' `sys.modules` swap depends on it
    # staying that way.
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — see above
        get_runtime_adapter_for_model,
    )

    adapter = get_runtime_adapter_for_model(model)
    return adapter.value if adapter else None


def filter_unsupported_effort(runtime_adapter: str | None, model: str | None, effort: str | None) -> str | None:
    """Drop an effort the given model doesn't support (e.g. a user saved `high` on a
    thinking model and then picked a non-thinking one).

    The single answer to "is this effort legal for this pair" — every stored-preference
    resolver routes through it.
    """
    # A missing adapter or model supports nothing: an unknown model must not inherit the
    # adapter's fallback ladder and quietly keep an effort the run would be rejected for.
    if not effort or not runtime_adapter or not model:
        return None
    return effort if effort in model_catalog.reasoning_efforts_for(runtime_adapter, model) else None


def label_for(value: str | None, mapping: dict[str, str]) -> str:
    """Display name for a stored value, falling back to the value itself."""
    if not value:
        return "—"
    return mapping.get(value, value)


__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "TASK_RUN_GATEWAY_PRODUCT",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "catalog_model_choices",
    "offered_model_choices",
    "plan_model_choices",
    "runnable_model_choices",
    "display_name_for_model",
    "filter_unsupported_effort",
    "group_by_runtime",
    "label_for",
    "runtime_adapter_for",
]
