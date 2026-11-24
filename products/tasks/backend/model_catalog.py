"""The choices a task agent run is configured with.

The hand-made half of model configuration: the runtime adapters and reasoning tiers, which
model families each product may call, how many versions of a family a picker offers, the
default models and the slider rungs. A model's own facts (its adapter, name, reasoning
efforts, context window and price) are not here. They come from the AI gateway listing,
through ``products.tasks.backend.logic.services.model_catalogue``.

The TypeScript sides read the same choices from two generated files,
``products/tasks/frontend/modelCatalog.generated.ts`` and
``packages/agent/packages/agent-contracts/src/model-catalog.generated.ts``. Both are emitted by
``products/tasks/scripts/model_catalog_projection.py`` and checked for drift by
`hogli build:projections --check` in CI. After editing this file, run `hogli build:projections`
and commit the result.

Keep this module free of Django and of anything outside the standard library. The
generator loads it by filesystem path with ``runpy``, which bypasses ``posthog``'s package
import and the Celery and settings machinery behind it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

CLAUDE = "claude"
CODEX = "codex"

ACP = "acp"
PI = "pi"

ANTHROPIC = "anthropic"
OPENAI = "openai"

# Which vendor API a runtime adapter speaks. The adapter drives the harness; the provider
# tells the agent server and the LLM gateway how to route.
PROVIDER_BY_RUNTIME_ADAPTER: dict[str, str] = {
    CLAUDE: ANTHROPIC,
    CODEX: OPENAI,
}

API_SHAPE_BY_RUNTIME_ADAPTER: dict[str, str] = {
    CLAUDE: "anthropic-messages",
    CODEX: "openai-responses",
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

# What a picker calls each tier. Sentence case, like every other label in the product.
REASONING_EFFORT_LABELS: dict[str, str] = {
    LOW: "Low",
    MEDIUM: "Medium",
    HIGH: "High",
    XHIGH: "Extra high",
    MAX: "Max",
    ULTRACODE: "Ultracode",
}

_THROUGH_MAX = (LOW, MEDIUM, HIGH, XHIGH, MAX)


@dataclass(frozen=True)
class ModelCost:
    """Base list price in US dollars per million tokens, not PostHog's negotiated rate.

    A picker states a comparison between models, and a negotiated rate would make it one
    nobody outside PostHog could check.
    """

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class RuntimeOption:
    """One entry a harness picker shows.

    The harness and the runtime adapter are not the same choice. The harness says which agent
    program runs the task; the adapter says which vendor protocol ACP speaks, and Pi has none,
    so ``runtime_adapter`` is ``None`` there. A picker shows one flat list, so this is where
    the two choices become one set of entries, once, instead of in each picker.
    """

    runtime: str
    runtime_adapter: str | None
    label: str


RUNTIME_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(ACP, CLAUDE, "Claude Code"),
    RuntimeOption(ACP, CODEX, "Codex"),
    RuntimeOption(PI, None, "Pi"),
)


AGENT_MODEL_FAMILIES: frozenset[str] = frozenset(
    {
        "claude-fable",
        "claude-opus",
        "claude-sonnet",
        "gpt",
        "gpt-astra",
        "gpt-luna",
        "gpt-sol",
        "gpt-terra",
        "kimi-pro",
    }
)

# The gateway lists the DeepSeek models under no family, so each one stands as a family of its own.
HOSTED_MODEL_FAMILIES: frozenset[str] = frozenset(
    {
        "glm",
        "glm-flash",
        "deepseek-ai/deepseek-v4.1-flash-1017",
        "deepseek-ai/deepseek-v4.1-flash-1017-fast",
    }
)

PRODUCT_MODEL_FAMILIES: dict[str, frozenset[str]] = {
    "posthog_ai": AGENT_MODEL_FAMILIES,
    "account_audit": AGENT_MODEL_FAMILIES,
    "autoresearch": AGENT_MODEL_FAMILIES,
    "background_agents": AGENT_MODEL_FAMILIES,
    "posthog_code": AGENT_MODEL_FAMILIES | HOSTED_MODEL_FAMILIES,
    "review_hog": AGENT_MODEL_FAMILIES | HOSTED_MODEL_FAMILIES,
    "slack_app": AGENT_MODEL_FAMILIES,
    "workflows": AGENT_MODEL_FAMILIES,
}

RESERVED_MODEL_PRODUCTS: dict[str, frozenset[str]] = {
    # Superseded by Kimi K3.1 Pro and DeepSeek V4.1 Flash. Runs already pinned to them keep working.
    "moonshotai/kimi-k3": frozenset(PRODUCT_MODEL_FAMILIES),
    "deepseek-ai/deepseek-v4-flash-0731": frozenset({"posthog_code", "review_hog"}),
    # The free tier and older PostHog Desktop builds call these.
    "zai-org/glm-5.2": frozenset({"posthog_code"}),
    "gpt-5.4": frozenset({"posthog_code"}),
    "gpt-5.3-codex": frozenset({"posthog_code"}),
    "gpt-5-mini": frozenset({"posthog_code"}),
    # Only ReviewHog's arm-set trial and the first-report model experiment call it.
    "gpt-6.1-terra": frozenset({"review_hog", "signals_scout"}),
}

MODEL_FAMILY_ACCESS_FLAGS: dict[str, str] = {}

OFFERED_VERSIONS_PER_FAMILY = 2

# The desktop app and its agent trim the gateway listing themselves, so they read this product's families.
CLIENT_LISTING_PRODUCT = "posthog_code"

# Applied when a run or a loop leaves the model unset: blank means "let PostHog pick", so the
# choice can improve without rewriting anything stored.
DEFAULT_MODEL_BY_RUNTIME_ADAPTER: dict[str, str] = {
    CLAUDE: "claude-sonnet-5-5",
    CODEX: "gpt-6.2-sol",
}


@dataclass(frozen=True)
class CapabilityNotch:
    """One stop on a picker's Faster → Smarter slider: a model and the depth it runs at.

    The rungs are a curated ordering over two dimensions, chosen so each is worth its extra
    cost over the one below, rather than anything derivable from the gateway listing.
    """

    model: str
    effort: str


# Cheapest first. A consumer filters these against what the gateway serves before rendering,
# so a rung naming a retired model drops out instead of becoming a stop that fails on send.
CAPABILITY_LADDER_BY_RUNTIME_ADAPTER: dict[str, tuple[CapabilityNotch, ...]] = {
    CLAUDE: (
        CapabilityNotch("claude-sonnet-5-5", MEDIUM),
        CapabilityNotch("claude-sonnet-5-5", HIGH),
        CapabilityNotch("claude-opus-5-5", MEDIUM),
        CapabilityNotch("claude-opus-5-5", XHIGH),
        CapabilityNotch("claude-fable-5-1", MAX),
    ),
    CODEX: (
        CapabilityNotch("gpt-6-luna", LOW),
        CapabilityNotch("gpt-6.2-sol", LOW),
        CapabilityNotch("gpt-6.2-sol", MEDIUM),
        CapabilityNotch("gpt-6.2-sol", HIGH),
        CapabilityNotch("gpt-6.2-sol", XHIGH),
        CapabilityNotch("gpt-6-astra", MAX),
    ),
}


RUNTIME_ADAPTERS: tuple[str, ...] = tuple(PROVIDER_BY_RUNTIME_ADAPTER)

RUNTIMES: tuple[str, ...] = tuple(dict.fromkeys(option.runtime for option in RUNTIME_OPTIONS))


def runtime_adapter_for_api_shapes(api_shapes: Iterable[str]) -> str | None:
    served = set(api_shapes)
    return next((adapter for adapter, shape in API_SHAPE_BY_RUNTIME_ADAPTER.items() if shape in served), None)


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


def gateway_model_id(model_id: str) -> str:
    return normalize_model_id(model_id).removeprefix("@cf/")


def is_anthropic_served_model(model_id: str | None) -> bool:
    """Whether Anthropic's API may serve this model, so its server can run the auto mode classifier checks."""
    return normalize_model_id(model_id or "").startswith("claude-")


_VERSION_SEGMENT = re.compile(r"-\d[\d.]*(?=-|$)")


def model_line(model_id: str) -> str:
    return _VERSION_SEGMENT.sub("", normalize_model_id(model_id))


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


# A mid-range anchor, so both the cheap end and the expensive end read as a useful ratio.
COST_BASELINE_MODEL = "claude-sonnet-5"

# Past this divergence between the input and output ratios, one number stops describing both
# and the multiplier is marked approximate rather than dropped.
_COST_RATIO_TOLERANCE = 0.1


def cost_multiplier_for(cost: ModelCost, baseline: ModelCost) -> tuple[float, bool]:
    """This model's per-token cost relative to the baseline, and whether it is approximate.

    Input and output rarely scale together, so one multiplier is the mean of both ratios.
    """
    input_ratio = cost.input_per_mtok / baseline.input_per_mtok
    output_ratio = cost.output_per_mtok / baseline.output_per_mtok
    spread = abs(input_ratio - output_ratio) / max(input_ratio, output_ratio)
    return (input_ratio + output_ratio) / 2, spread > _COST_RATIO_TOLERANCE


def _format_multiplier(multiplier: float) -> str:
    """Round to the precision that stays meaningful at this magnitude: `5×`, `1.5×`, `0.06×`."""
    if multiplier >= 10:
        return str(round(multiplier))
    if multiplier >= 0.95:
        one_decimal = round(multiplier, 1)
        return str(int(one_decimal)) if one_decimal.is_integer() else f"{one_decimal:.1f}"
    return str(round(multiplier, 2))


def cost_multiplier_label_for_cost(cost: ModelCost, baseline: ModelCost) -> str:
    multiplier, approximate = cost_multiplier_for(cost, baseline)
    return f"{'≈' if approximate else ''}{_format_multiplier(multiplier)}×"


def format_cost_rates(cost: ModelCost) -> str:
    def money(amount: float) -> str:
        return f"${amount:.0f}" if float(amount).is_integer() else f"${amount:.2f}"

    return f"Input {money(cost.input_per_mtok)} · Output {money(cost.output_per_mtok)} per 1M tokens"


def reasoning_efforts_from_provider(model_id: str, provider_efforts: Iterable[str]) -> tuple[str, ...]:
    listed = set(provider_efforts)
    efforts = tuple(effort for effort in _THROUGH_MAX if effort in listed)
    if XHIGH in listed and is_anthropic_served_model(model_id):
        return (*efforts, ULTRACODE)
    return efforts
