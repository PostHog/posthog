"""Which models a task run may use, and how to name them.

The catalogue is the live LLM-gateway model list for a gateway product, intersected
with the runtime adapters this product knows how to drive. Anything the gateway serves
under a provider we can't route — bedrock, vertex — is dropped rather than offered.

Every surface that offers a model picker derives from here: the task composer in the
web app (`posthog_code`), the Slack App Home picker and the model-override classifier
(`slack_app`). None of them may hardcode a model list, and none of them owns the
display labels — a new model ships by appearing on the gateway, not by a PR per
surface.

The gateway is fetched through Django's shared cache so a picker render never blocks on
a round-trip; the timeout is capped at 3s because Slack's interactivity path expires
`trigger_id` after ~3s, and failures are negatively cached for 30s so a broken gateway
can't make every interaction wait the full timeout.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from products.tasks.backend import model_catalog
from products.tasks.backend.logic.services.gateway_model_pin import admitted_listing, agent_models, offered_listing
from products.tasks.backend.logic.services.gateway_models import GatewayModel, known_gateway_models, list_gateway_models
from products.tasks.backend.model_catalog import COST_BASELINE_MODEL

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


_ALIAS_NAME_SUFFIX = " (latest)"

_RUNTIME_ADAPTER_BY_PROVIDER: dict[str, str] = {
    provider: adapter for adapter, provider in model_catalog.PROVIDER_BY_RUNTIME_ADAPTER.items()
}


def _listing() -> tuple[GatewayModel, ...]:
    return known_gateway_models(TASK_RUN_GATEWAY_PRODUCT)


def listed_model(model: str | None) -> GatewayModel | None:
    if not model:
        return None
    listed_id = model_catalog.gateway_model_id(model)
    return next((listed for listed in _listing() if listed.id == listed_id), None)


def _runtime_adapter(listed: GatewayModel) -> str | None:
    if listed.api_shapes:
        return model_catalog.runtime_adapter_for_api_shapes(listed.api_shapes)
    return _RUNTIME_ADAPTER_BY_PROVIDER.get(listed.owned_by)


def _name_from_id(model: str) -> str:
    return model_catalog.format_model_id(model.rsplit("/", 1)[-1])


def _display_name(listed: GatewayModel) -> str:
    return listed.name.removesuffix(_ALIAS_NAME_SUFFIX) or _name_from_id(listed.id)


def _efforts(listed: GatewayModel) -> tuple[str, ...]:
    return model_catalog.reasoning_efforts_from_provider(listed.id, listed.reasoning_efforts or ())


def _cost(listed: GatewayModel | None) -> model_catalog.ModelCost | None:
    if listed is None or not listed.input_per_mtok or not listed.output_per_mtok:
        return None
    return model_catalog.ModelCost(listed.input_per_mtok, listed.output_per_mtok)


def _choices(rows: Iterable[GatewayModel], listing: tuple[GatewayModel, ...]) -> tuple[ModelChoice, ...]:
    baseline = _cost(next((listed for listed in listing if listed.id == COST_BASELINE_MODEL), None))
    choices = []
    for listed in rows:
        runtime_adapter = _runtime_adapter(listed)
        if runtime_adapter is None:
            continue
        cost = _cost(listed)
        choices.append(
            ModelChoice(
                runtime_adapter=runtime_adapter,
                model=listed.id,
                label=_display_name(listed),
                supported_efforts=_efforts(listed),
                cost_multiplier=model_catalog.cost_multiplier_label_for_cost(cost, baseline)
                if cost and baseline
                else None,
            )
        )
    return tuple(choices)


def available_model_choices(product: Product) -> tuple[ModelChoice, ...]:
    """Every model a run on the given gateway product may use.

    Empty when the gateway is unreachable — callers must treat that as "no choice to
    offer" rather than falling back to a hardcoded list, so a gateway outage can't route
    a run to a model the gateway would reject anyway.
    """
    listing = list_gateway_models(product)
    return _choices(offered_listing(product, listing), listing)


def supported_efforts(runtime_adapter: str, model: str) -> tuple[str, ...]:
    listed = listed_model(model)
    if listed is None or _runtime_adapter(listed) != runtime_adapter:
        return ()
    return _efforts(listed)


def _undescribed_efforts(runtime_adapter: str, model: str) -> tuple[str, ...]:
    efforts = model_catalog.reasoning_efforts_from_provider(model, model_catalog.REASONING_EFFORTS)
    if runtime_adapter == model_catalog.CLAUDE:
        return efforts
    return tuple(effort for effort in efforts if effort != model_catalog.ULTRACODE)


def takes_reasoning_effort(runtime_adapter: str, model: str, effort: str) -> bool:
    listed = listed_model(model)
    if listed is None:
        return effort in _undescribed_efforts(runtime_adapter, model)
    if _runtime_adapter(listed) != runtime_adapter:
        return False
    if listed.reasoning_efforts is None:
        return effort in _undescribed_efforts(runtime_adapter, model)
    return effort in _efforts(listed)


def display_name_for_model(model: str) -> str:
    listed = listed_model(model)
    return _display_name(listed) if listed else _name_from_id(model)


def known_model_choices() -> tuple[ModelChoice, ...]:
    listing = _listing()
    return _choices(agent_models(listing), listing)


def product_model_choices(product: str, *, offered_only: bool) -> tuple[ModelChoice, ...]:
    listing = _listing()
    rows = offered_listing(product, listing) if offered_only else admitted_listing(product, listing)
    return _choices(rows, listing)


def offered_model_choices() -> tuple[ModelChoice, ...]:
    return product_model_choices(TASK_RUN_GATEWAY_PRODUCT, offered_only=True)


def models_for_runtime_adapter(runtime_adapter: str) -> tuple[str, ...]:
    return tuple(listed.id for listed in agent_models(_listing()) if _runtime_adapter(listed) == runtime_adapter)


def runtime_adapter_for(model: str | None) -> str | None:
    listed = listed_model(model)
    return _runtime_adapter(listed) if listed else None


def filter_unsupported_effort(runtime_adapter: str | None, model: str | None, effort: str | None) -> str | None:
    """Drop an effort the given model doesn't support (e.g. a user saved `high` on a
    thinking model and then picked a non-thinking one).

    The single answer to "is this effort legal for this pair" — every stored-preference
    resolver routes through it.
    """
    if not effort or not runtime_adapter or not model:
        return None
    return effort if takes_reasoning_effort(runtime_adapter, model, effort) else None


def label_for(value: str | None, mapping: dict[str, str]) -> str:
    """Display name for a stored value, falling back to the value itself."""
    if not value:
        return "—"
    return mapping.get(value, value)


__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "TASK_RUN_GATEWAY_PRODUCT",
    "GatewayModel",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "known_model_choices",
    "models_for_runtime_adapter",
    "offered_model_choices",
    "product_model_choices",
    "display_name_for_model",
    "filter_unsupported_effort",
    "group_by_runtime",
    "label_for",
    "list_gateway_models",
    "listed_model",
    "runtime_adapter_for",
    "supported_efforts",
    "takes_reasoning_effort",
]
