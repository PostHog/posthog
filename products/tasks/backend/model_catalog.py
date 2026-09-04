"""The models a task agent run may use, and what each one supports.

This module is the single definition of the run triple — runtime adapter, model, and
reasoning effort — together with the model each adapter falls back to when a run pins
none. Every surface that offers or validates a selection derives from here:

- the backend, through ``products.tasks.backend.temporal.process_task.utils``;
- the web composer and settings, through ``products/tasks/frontend/modelCatalog.generated.ts``;
- the desktop app and its agent, through ``@posthog/shared/model-catalog``.

Both TypeScript projections are emitted by ``products/tasks/scripts/build_model_catalog.py`` and are
checked for drift by the same CI job that guards the generated OpenAPI types, so a model
ships by editing this file and nothing else.

Keep this module free of Django and of anything outside the standard library. The
generator loads it by filesystem path with ``runpy``, which bypasses ``posthog``'s package
import and the Celery and settings machinery behind it.
"""

from __future__ import annotations

from dataclasses import dataclass

CLAUDE = "claude"
CODEX = "codex"

ANTHROPIC = "anthropic"
OPENAI = "openai"

# Which vendor API a runtime adapter speaks. The adapter drives the harness; the provider
# tells the agent server and the LLM gateway how to route.
PROVIDER_BY_RUNTIME_ADAPTER: dict[str, str] = {
    CLAUDE: ANTHROPIC,
    CODEX: OPENAI,
}

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
XHIGH = "xhigh"
MAX = "max"
ULTRACODE = "ultracode"

# Every tier any model exposes, shallowest first. A consumer renders an effort ladder from
# this, so a new tier reaches both projections by being added here and nowhere else.
REASONING_EFFORTS: tuple[str, ...] = (LOW, MEDIUM, HIGH, XHIGH, MAX, ULTRACODE)

_STANDARD = (LOW, MEDIUM, HIGH)
_THROUGH_MAX = (*_STANDARD, XHIGH, MAX)
_EXTENDED = (*_THROUGH_MAX, ULTRACODE)
# The GLM family exposes two thinking depths rather than the full ladder.
_GLM = (HIGH, MAX)
_NO_EFFORT: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogModel:
    """One model a run may use.

    ``reasoning_efforts`` is empty for a model with no effort control. That is an answer,
    not missing metadata: a picker renders such a model without an effort dropdown, and a
    run must not send an effort for it.
    """

    id: str
    runtime_adapter: str
    reasoning_efforts: tuple[str, ...]


MODELS: tuple[CatalogModel, ...] = (
    # GLM 5.2 is Cloudflare-served and driven through the `claude` adapter: the LLM gateway
    # exposes it over its Anthropic-Messages surface and translates the `@cf/` id upstream,
    # so the `anthropic` provider is the intended routing rather than a direct Anthropic call.
    CatalogModel("@cf/zai-org/glm-5.2", CLAUDE, _GLM),
    CatalogModel("zai-org/glm-5.3", CLAUDE, _GLM),
    CatalogModel("zai-org/glm-5.3-flash", CLAUDE, _GLM),
    CatalogModel("moonshotai/kimi-k3", CLAUDE, _NO_EFFORT),
    CatalogModel("claude-opus-4-5", CLAUDE, _STANDARD),
    CatalogModel("claude-opus-4-6", CLAUDE, _THROUGH_MAX),
    CatalogModel("claude-opus-4-7", CLAUDE, _EXTENDED),
    CatalogModel("claude-opus-4-8", CLAUDE, _EXTENDED),
    CatalogModel("claude-opus-5", CLAUDE, _EXTENDED),
    CatalogModel("claude-fable-5", CLAUDE, _EXTENDED),
    CatalogModel("claude-fable-5-1", CLAUDE, _EXTENDED),
    CatalogModel("claude-sonnet-5", CLAUDE, _EXTENDED),
    CatalogModel("claude-sonnet-4-6", CLAUDE, _STANDARD),
    CatalogModel("gpt-5", CODEX, _STANDARD),
    CatalogModel("gpt-5.5", CODEX, (*_STANDARD, XHIGH)),
    CatalogModel("gpt-5.6-sol", CODEX, _THROUGH_MAX),
    CatalogModel("gpt-5.6-terra", CODEX, _THROUGH_MAX),
    CatalogModel("gpt-5.6-luna", CODEX, _THROUGH_MAX),
)

# Depths a whole model family exposes, used when no exact id matches. OpenAI ships
# vendor-flavoured variants the gateway never lists (`gpt-5.5-codex`), and a desktop session
# running against the user's own subscription can drive one, so the tier a family supports has
# to answer for those too. The longest matching prefix wins, so declaration order is free.
FAMILY_REASONING_EFFORTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (CODEX, "gpt-5.6", _THROUGH_MAX),
    (CODEX, "gpt-5.5", (*_STANDARD, XHIGH)),
)

# What a runtime accepts for a model neither an id nor a family claims. Codex passes any
# `gpt-*` identifier through to the runtime, so an id the gateway starts serving before it is
# listed here still runs, at the depths every Codex model supports. Claude is absent on
# purpose: an unnamed model there yields no efforts, which is what makes validation reject one.
FALLBACK_REASONING_EFFORTS_BY_RUNTIME_ADAPTER: dict[str, tuple[str, ...]] = {
    CODEX: _STANDARD,
}

# Applied when a run or a loop leaves the model unset: blank means "let PostHog pick", so the
# choice can improve without rewriting anything stored.
DEFAULT_MODEL_BY_RUNTIME_ADAPTER: dict[str, str] = {
    CLAUDE: "claude-sonnet-5",
    CODEX: "gpt-5",
}


RUNTIME_ADAPTERS: tuple[str, ...] = tuple(PROVIDER_BY_RUNTIME_ADAPTER)


def models_for_runtime_adapter(runtime_adapter: str) -> tuple[str, ...]:
    """The model ids one adapter drives, in catalog order."""
    return tuple(model.id for model in MODELS if model.runtime_adapter == runtime_adapter)


def normalize_model_id(model_id: str) -> str:
    """The form a model id is looked up under.

    The LLM gateway serves some models both bare and provider-qualified
    (``openai/gpt-5.6-sol``), and a picker may hand back either. Folding the two together
    is what stops the same model from having two answers depending on which surface asked.
    Only the provider prefixes this catalog knows are stripped, so ids that carry a slash
    of their own (``@cf/zai-org/glm-5.2``) survive intact.
    """
    normalized = model_id.strip().lower()
    for provider in PROVIDER_BY_RUNTIME_ADAPTER.values():
        prefix = f"{provider}/"
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def reasoning_efforts_for(runtime_adapter: str, model_id: str) -> tuple[str, ...]:
    """The efforts this model may run at, empty when it takes no effort at all.

    Resolved in three steps: the exact id, then the family it belongs to, then what the
    adapter accepts generally. Codex passes any ``gpt-*`` identifier through, so a newly
    served id still runs, while Claude has no fallback and yields nothing — which is what
    makes validation reject it.
    """
    normalized = normalize_model_id(model_id)
    for model in MODELS:
        if model.runtime_adapter == runtime_adapter and model.id == normalized:
            return model.reasoning_efforts
    families = [
        (prefix, efforts)
        for adapter, prefix, efforts in FAMILY_REASONING_EFFORTS
        if adapter == runtime_adapter and normalized.startswith(prefix)
    ]
    if families:
        return max(families, key=lambda family: len(family[0]))[1]
    return FALLBACK_REASONING_EFFORTS_BY_RUNTIME_ADAPTER.get(runtime_adapter, ())


__all__ = [
    "ANTHROPIC",
    "CLAUDE",
    "CODEX",
    "DEFAULT_MODEL_BY_RUNTIME_ADAPTER",
    "FALLBACK_REASONING_EFFORTS_BY_RUNTIME_ADAPTER",
    "MODELS",
    "OPENAI",
    "PROVIDER_BY_RUNTIME_ADAPTER",
    "REASONING_EFFORTS",
    "RUNTIME_ADAPTERS",
    "CatalogModel",
    "models_for_runtime_adapter",
    "normalize_model_id",
    "reasoning_efforts_for",
]
