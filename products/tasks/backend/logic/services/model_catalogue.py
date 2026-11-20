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

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from products.tasks.backend import model_catalog
from products.tasks.backend.logic.services.gateway_model_pin import model_allowed_by_product_pin
from products.tasks.backend.logic.services.gateway_models import (
    GatewayModel,
    cached_gateway_models,
    list_gateway_models,
)
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
    """Every model a run on the given gateway product may use.

    Empty when the gateway is unreachable — callers must treat that as "no choice to
    offer" rather than falling back to a hardcoded list, so a gateway outage can't route
    a run to a model the gateway would reject anyway.
    """
    # Deferred because `temporal.process_task.utils` pulls the tasks ORM, mcp_store, and
    # sandbox config at import time; keeping that off the import path of every catalogue
    # consumer is the reason, and the App Home tests' `sys.modules` swap depends on it
    # staying that way.
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — see above
        get_supported_reasoning_efforts,
    )

    by_provider = _runtime_adapter_by_provider()
    choices = []
    for model in list_gateway_models(product):
        if not model_allowed_by_product_pin(product, model.id):
            continue
        # The catalog names the harness that drives a model; `owned_by` names whoever
        # serves it, which for the vendor-served models is `cloudflare`/`baseten`/the
        # vendor org and says nothing about the harness. Falling back to the provider
        # keeps an unlisted `gpt-*` working and still drops a provider we cannot route.
        runtime_adapter = runtime_adapter_for(model.id) or by_provider.get(model.owned_by)
        if runtime_adapter is None:
            continue
        if model_catalog.runtime_adapter_for_model(model.id) is None:
            choices.append(_listed_choice(runtime_adapter, model))
            continue
        choices.append(
            ModelChoice(
                runtime_adapter=runtime_adapter,
                model=model.id,
                label=model_catalog.display_name_for_model(model.id),
                supported_efforts=tuple(e.value for e in get_supported_reasoning_efforts(runtime_adapter, model.id)),
                cost_multiplier=model_catalog.cost_multiplier_label(model.id),
            )
        )
    return tuple(choices)


_ALIAS_NAME_SUFFIX = " (latest)"


def _listed_choice(runtime_adapter: str, listed: GatewayModel) -> ModelChoice:
    return ModelChoice(
        runtime_adapter=runtime_adapter,
        model=listed.id,
        label=listed.name.removesuffix(_ALIAS_NAME_SUFFIX) or model_catalog.format_model_id(listed.id),
        supported_efforts=_listed_efforts(runtime_adapter, listed),
        cost_multiplier=_listed_cost_multiplier(listed),
    )


def _listed_efforts(runtime_adapter: str, listed: GatewayModel) -> tuple[str, ...]:
    if listed.reasoning_efforts is None:
        return model_catalog.reasoning_efforts_for(runtime_adapter, listed.id)
    return model_catalog.reasoning_efforts_from_provider(listed.id, listed.reasoning_efforts)


def _listed_cost_multiplier(listed: GatewayModel) -> str | None:
    if not listed.input_per_mtok or not listed.output_per_mtok:
        return None
    return model_catalog.cost_multiplier_label_for_cost(
        model_catalog.ModelCost(listed.input_per_mtok, listed.output_per_mtok)
    )


def supported_efforts(runtime_adapter: str, model: str) -> tuple[str, ...]:
    if model_catalog.runtime_adapter_for_model(model) is None:
        normalized = model_catalog.normalize_model_id(model)
        for listed in cached_gateway_models(TASK_RUN_GATEWAY_PRODUCT):
            if listed.id == normalized:
                return _listed_efforts(runtime_adapter, listed)
    return model_catalog.reasoning_efforts_for(runtime_adapter, model)


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
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — see `available_model_choices`
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
    return effort if effort in supported_efforts(runtime_adapter, model) else None


@lru_cache(maxsize=1)
def _runtime_adapter_by_provider() -> dict[str, str]:
    """Gateway `owned_by` → runtime adapter.

    Inverted from the adapter → provider mapping rather than written out here, so the
    two can never disagree about which runtime serves a provider. Providers with no
    adapter (bedrock, vertex) are simply absent, which is what drops their models from
    the catalogue.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — see `available_model_choices`
        RuntimeAdapter,
        get_provider_for_runtime_adapter,
    )

    by_provider = {}
    for adapter in RuntimeAdapter:
        provider = get_provider_for_runtime_adapter(adapter)
        if provider is not None:
            by_provider[provider.value] = adapter.value
    return by_provider


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
    "catalog_model_choices",
    "offered_model_choices",
    "display_name_for_model",
    "filter_unsupported_effort",
    "group_by_runtime",
    "label_for",
    "list_gateway_models",
    "runtime_adapter_for",
    "supported_efforts",
]
