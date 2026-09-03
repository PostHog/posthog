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

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from django.core.cache import cache

import structlog

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

logger = structlog.get_logger(__name__)

# The gateway product a user-initiated task run authenticates as — the same one the
# sandbox agent uses, so the picker can only ever offer models the run itself may call.
TASK_RUN_GATEWAY_PRODUCT: Product = "posthog_code"

_CACHE_KEY_PREFIX = "tasks:llm_gateway_models"
_CACHE_TTL_SECONDS = 30 * 60
_NEGATIVE_CACHE_TTL_SECONDS = 30
_FETCH_TIMEOUT_SECONDS = 3.0

# Runtime + effort labels are UI strings with no run-config equivalent. Model display
# labels are computed from the model id on the fly via `format_model_id` so we never
# have to hand-maintain a model→label map.
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

# Vendor initialisms that must not be title-cased into "Gpt".
_MODEL_ACRONYMS: dict[str, str] = {"gpt": "GPT", "glm": "GLM"}


@dataclass(frozen=True)
class GatewayModel:
    id: str
    owned_by: str
    context_window: int


@dataclass(frozen=True)
class ModelChoice:
    """One model a run may use, with the efforts that model supports.

    `supported_efforts` is empty for a model with no effort control — that is a real
    answer, not missing metadata, so a picker should render the model with no effort
    dropdown rather than hiding it.
    """

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


def _cache_quietly(key: str, value: tuple[GatewayModel, ...], timeout: int) -> None:
    """Caching is an optimization — an unreachable cache must not fail the caller."""
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.exception("tasks_llm_gateway_models_cache_write_failed", cache_key=key)


def list_gateway_models(product: Product) -> tuple[GatewayModel, ...]:
    """Return the model list the given gateway product exposes.

    Returns an empty tuple on any error, the cache included — a picker with no models is a
    worse day than a 500 for every caller. The empty result is briefly cached so subsequent
    calls during a gateway outage fail fast.
    """
    cache_key = f"{_CACHE_KEY_PREFIX}:{product}"

    # Deferred: `gateway_client` pulls the Anthropic and OpenAI SDKs, and this module is reachable from
    # the tasks API's import path — every other caller in the repo defers it for the same reason.
    from posthog.llm.gateway_client import get_llm_client  # noqa: PLC0415 — keeps the LLM SDKs off startup paths

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        page = get_llm_client(product=product).with_options(timeout=_FETCH_TIMEOUT_SECONDS).models.list()
    except Exception:
        logger.exception("tasks_llm_gateway_models_fetch_failed", gateway_product=product)
        _cache_quietly(cache_key, (), _NEGATIVE_CACHE_TTL_SECONDS)
        return ()

    models = tuple(
        GatewayModel(
            id=m.id,
            owned_by=getattr(m, "owned_by", ""),
            context_window=getattr(m, "context_window", 0),
        )
        for m in page.data
    )
    _cache_quietly(cache_key, models, _CACHE_TTL_SECONDS)
    return models


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
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — see `available_model_choices`
        get_supported_reasoning_efforts,
    )

    if not effort:
        return None
    return effort if effort in {e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)} else None


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


def format_model_id(model_id: str) -> str:
    """Turn a gateway model id into a display name: `Claude Opus 4.8`, `GPT-5.6 Sol`.

    Every family goes through the same rules — strip the provider prefix, glue a version
    onto a leading acronym, title-case the rest — so a new model is named without anyone
    touching a lookup table.
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
    # `gpt` + `5.6` reads as `GPT-5.6`, the way the vendor writes it, with any remaining
    # qualifier ("sol", "codex", "mini") as its own word.
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


__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "TASK_RUN_GATEWAY_PRODUCT",
    "GatewayModel",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "filter_unsupported_effort",
    "format_model_id",
    "group_by_runtime",
    "label_for",
    "list_gateway_models",
    "runtime_adapter_for",
]
