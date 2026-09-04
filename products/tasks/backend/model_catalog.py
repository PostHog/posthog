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

import re
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

    ``label`` is set only where deriving the name from the id gets it wrong. Each surface
    formats an id it has no label for, and those formatters disagree on vendor-qualified
    ids, so a model whose name matters is named here once instead of in each picker.
    """

    id: str
    runtime_adapter: str
    reasoning_efforts: tuple[str, ...]
    label: str | None = None


MODELS: tuple[CatalogModel, ...] = (
    # GLM 5.2 is Cloudflare-served and driven through the `claude` adapter: the LLM gateway
    # exposes it over its Anthropic-Messages surface and translates the `@cf/` id upstream,
    # so the `anthropic` provider is the intended routing rather than a direct Anthropic call.
    CatalogModel("@cf/zai-org/glm-5.2", CLAUDE, _GLM, label="GLM-5.2"),
    CatalogModel("zai-org/glm-5.3", CLAUDE, _GLM, label="GLM-5.3"),
    CatalogModel("zai-org/glm-5.3-flash", CLAUDE, _GLM, label="GLM-5.3 Flash"),
    CatalogModel("moonshotai/kimi-k3", CLAUDE, _NO_EFFORT, label="Kimi K3"),
    CatalogModel("deepseek-ai/deepseek-v4-flash-0731", CLAUDE, _NO_EFFORT, label="DeepSeek V4 Flash"),
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


def serves_model(runtime_adapter: str, model_id: str | None) -> bool:
    """Whether this adapter drives the model, whichever spelling the caller sends.

    Membership rather than the id tuple, because comparing against
    ``models_for_runtime_adapter`` directly means comparing raw strings: the gateway
    serves some models provider-qualified, so an allowlist built that way rejects a
    spelling every resolver here accepts.
    """
    if not model_id:
        return False
    return normalize_model_id(model_id) in models_for_runtime_adapter(runtime_adapter)


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


def label_for_model(model_id: str) -> str | None:
    """The name this catalog pins for a model id, or ``None`` to let the caller derive one."""
    normalized = normalize_model_id(model_id)
    for model in MODELS:
        if model.id == normalized:
            return model.label
    return None


_MODEL_ACRONYMS: dict[str, str] = {"gpt": "GPT", "glm": "GLM"}


def _titled(word: str) -> str:
    """Capitalise a name part, leaving bare version numbers alone."""
    if re.fullmatch(r"[0-9.]+", word):
        return word
    return word[:1].upper() + word[1:].lower()


def format_model_id(model_id: str) -> str:
    """Turn a gateway model id into a display name: `Claude Opus 4.8`, `GPT-5.6 Sol`.

    Every family goes through the same rules — strip the provider prefix, glue a version
    onto a leading acronym, title-case the rest — so a new model is named without anyone
    touching a lookup table.
    """
    # Collapse `4-8` into `4.8` so version components survive the dash split.
    clean = re.sub(r"(\d)-(\d)", r"\1.\2", normalize_model_id(model_id))
    words = re.split(r"[-_]", clean)
    acronym = _MODEL_ACRONYMS.get(words[0].lower())
    if acronym is None:
        return " ".join(_titled(word) for word in words)
    # `gpt` + `5.6` reads as `GPT-5.6`, the way the vendor writes it, with any remaining
    # qualifier ("sol", "codex", "mini") as its own word.
    head = f"{acronym}-{words[1]}" if len(words) > 1 else acronym
    return " ".join([head, *(_titled(word) for word in words[2:])])


def display_name_for_model(model_id: str) -> str:
    """The name a picker shows for a model.

    The catalog's own name where it pins one, and the name derived from the id everywhere
    else. Every surface resolves a display name through here, so a model reads the same in
    the web composer, the Slack picker, and the desktop app.
    """
    return label_for_model(model_id) or format_model_id(model_id)


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
    "label_for_model",
    "models_for_runtime_adapter",
    "normalize_model_id",
    "display_name_for_model",
    "format_model_id",
    "reasoning_efforts_for",
    "serves_model",
]
