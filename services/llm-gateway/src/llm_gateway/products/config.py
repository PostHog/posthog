from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fastapi import HTTPException

from llm_gateway.bedrock import BEDROCK_MODEL_IDS, get_bedrock_model_access_candidates, get_bedrock_region_name
from llm_gateway.config import get_settings


class CreditBucket(StrEnum):
    """Customer credit bucket a product's generations bill into.

    Values match (or, once created, will match) the Django quota resource keys
    (ee/billing/quota_limiting.py QuotaResource), which is what the gateway's
    quota resolver checks against. Only AI_CREDITS has a QuotaResource and
    gateway-side quota enforcement today; POSTHOG_CODE_CREDITS bills without
    blocking until its resource lands.
    """

    AI_CREDITS = "ai_credits"
    POSTHOG_CODE_CREDITS = "posthog_code_credits"


@dataclass(frozen=True)
class ProductConfig:
    # Empty set (the default) or None means no OAuth application is authorized for this product.
    # To permit OAuth access, explicitly list the allowed application IDs.
    allowed_application_ids: frozenset[str] | None = frozenset()
    allowed_models: frozenset[str] | None = None  # None = all allowed
    allow_api_keys: bool = True
    # Which customer credit bucket this product bills into. None = not billed: emitted
    # $ai_generation events are tagged $ai_billable=false and the usage reporter
    # (posthog/tasks/usage_report.py) ignores them. A bucket value tags events billable
    # so the reporter rolls them into that bucket's credit counter, and requests are
    # blocked when the bucket's quota is exhausted — currently only AI_CREDITS has
    # gateway-side quota enforcement; other buckets bill without blocking.
    credit_bucket: CreditBucket | None = None


BEDROCK_MODELS = BEDROCK_MODEL_IDS

# OAuth application IDs per region
POSTHOG_CODE_US_APP_ID = "019a3066-4aa2-0000-ca70-48ecdcc519cf"
POSTHOG_CODE_EU_APP_ID = "019a3067-5be7-0000-33c7-c6743eb59a79"
POSTHOG_CODE_DEV_APP_ID = "019ebb47-c750-0000-e1ea-723a6ff112d3"
TWIG_US_APP_ID = POSTHOG_CODE_US_APP_ID
TWIG_EU_APP_ID = POSTHOG_CODE_EU_APP_ID
WIZARD_US_APP_ID = "019a0c79-b69d-0000-f31b-b41345208c9d"
WIZARD_EU_APP_ID = "019a12d0-6edd-0000-0458-86616af3a3db"
POSTHOG_AI_US_APP_ID = "019ee060-3a0e-0000-7e9c-4e6b48dfae66"
POSTHOG_AI_EU_APP_ID = "019ee061-5620-0000-1a0d-ab1160fceeb1"
POSTHOG_AI_DEV_APP_ID = "019edb1a-cce4-0000-1f6d-682061862da9"

# Shared by `posthog_code` and `slack_app` — the agent that runs in the sandbox
# is the same code regardless of where the task was initiated, so the model
# allowlist is identical.
_POSTHOG_CODE_AGENT_MODELS: Final[frozenset[str]] = frozenset(
    {
        "claude-opus-4-5",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.2",
        "gpt-5-mini",
        "@cf/zai-org/glm-5.2",
    }
)

PRODUCTS: Final[dict[str, ProductConfig]] = {
    "llm_gateway": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    # CI / end-to-end test runs (e.g. posthog/code agent e2e tests). Authenticates with a
    # personal API key, allows all models, and keeps CI traffic attributed to its own
    # ai_product rather than the catch-all llm_gateway bucket.
    "ci": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "posthog_code": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=_POSTHOG_CODE_AGENT_MODELS | BEDROCK_MODELS,
        allow_api_keys=False,
        # Bills as posthog_code credits (pass-through model costs, no markup) — see
        # get_teams_with_posthog_code_credits_used_in_period in posthog/tasks/usage_report.py.
        credit_bucket=CreditBucket.POSTHOG_CODE_CREDITS,
    ),
    # PostHog-initiated internal task runs (Task.internal=True without a more specific
    # origin route — e.g. the repo-selection agent). Deliberately unbilled: this is
    # "work completed by PostHog" per the pricing RFC, which gets its own (marked-up)
    # pricing later rather than posthog_code's pass-through bucket. Interim spend
    # control is the product/user cost limits in llm_gateway/config.py.
    "background_agents": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=frozenset(
            {
                "claude-opus-4-5",
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-opus-4-8",
                "claude-fable-5",
                "claude-sonnet-4-5",
                "claude-sonnet-5",
                "claude-haiku-4-5",
                "gpt-5.4",
                "gpt-5.3-codex",
                "gpt-5.2",
                "gpt-5-mini",
            }
            | BEDROCK_MODELS
        ),
        allow_api_keys=False,
        credit_bucket=None,
    ),
    "slack_app": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=_POSTHOG_CODE_AGENT_MODELS | BEDROCK_MODELS,
        allow_api_keys=False,
        credit_bucket=CreditBucket.AI_CREDITS,
    ),
    # SherlockHog (https://github.com/PostHog/SherlockHog) — the internal SRE
    # bot. Authenticates with a personal API key (not OAuth), so no application
    # IDs are needed. It pins claude-opus-4-8 but can be repointed via
    # ANTHROPIC_MODEL and uses Bedrock fallback, so all models are permitted.
    # Internal infra tooling — not billed to a customer credit bucket.
    "sherlockhog": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
        credit_bucket=None,
    ),
    "wizard": ProductConfig(
        allowed_application_ids=frozenset({WIZARD_US_APP_ID, WIZARD_EU_APP_ID}),
        allowed_models=None,
        allow_api_keys=True,
    ),
    "llma_labeling": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5.4"}),
        allow_api_keys=True,
    ),
    "django": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "slack_app_routing": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"claude-haiku-4-5"}),
        allow_api_keys=True,
        credit_bucket=CreditBucket.AI_CREDITS,
    ),
    "growth": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "llma_translation": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "llma_summarization": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-nano", "gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "llma_eval_summary": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5-mini"}),
        allow_api_keys=True,
    ),
    "customer_archetype_classification": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5-mini"}),
        allow_api_keys=True,
    ),
    "product_analytics": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "signals": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=None,  # any model — the signals pipeline picks models per stage (haiku, sonnet, ...)
        allow_api_keys=True,
        credit_bucket=None,
    ),
    "subscriptions": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "conversations": ProductConfig(
        # Sandbox support-reply tasks auth with the array (posthog_code) OAuth app but
        # route through this product so draft spend rolls up with utility prompts.
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=frozenset({"claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5"}),
        allow_api_keys=True,
        # Deliberately unbilled: autonomous support-reply drafting is "work completed by
        # PostHog" per the pricing RFC — it gets its own pricing later, not posthog_code's
        # pass-through bucket.
        credit_bucket=None,
    ),
    "warehouse_semantic_enrichment": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"claude-haiku-4-5"}),
        allow_api_keys=True,
        credit_bucket=None,
    ),
    # Drafts a Custom REST source manifest from API docs. Low volume, high stakes, long context —
    # pinned to Opus rather than the cheap per-row model the enrichment context layer uses.
    "warehouse_custom_source_builder": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"claude-opus-4-8"}),
        allow_api_keys=True,
        credit_bucket=None,
    ),
    "posthog_ai": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_AI_US_APP_ID, POSTHOG_AI_EU_APP_ID, POSTHOG_AI_DEV_APP_ID}),
        allowed_models=None,  # any model
        allow_api_keys=True,
        credit_bucket=CreditBucket.AI_CREDITS,
    ),
}


ALLOWED_PRODUCTS: Final[frozenset[str]] = frozenset(PRODUCTS.keys())

PRODUCT_ALIASES: Final[dict[str, str]] = {
    "array": "posthog_code",
    "twig": "posthog_code",
    "slack-posthog-code": "slack_app_routing",
    "slack-twig": "slack_app_routing",
}


def resolve_product_alias(product: str) -> str:
    return PRODUCT_ALIASES.get(product, product)


def get_product_config(product: str) -> ProductConfig | None:
    return PRODUCTS.get(resolve_product_alias(product))


def validate_product(product: str) -> str:
    resolved = resolve_product_alias(product)
    if resolved not in ALLOWED_PRODUCTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product '{product}'. Allowed products: {', '.join(sorted(ALLOWED_PRODUCTS))}",
        )
    return resolved


def _model_matches_product_allowlist(
    model: str,
    allowed_models: frozenset[str],
    provider: str | None = None,
    settings: object | None = None,
) -> bool:
    model_candidates = {model.lower()}
    if provider == "bedrock":
        model_candidates = set(
            get_bedrock_model_access_candidates(model, region_name=get_bedrock_region_name(settings=settings))
        )

    allowed_prefixes = tuple(allowed_model.lower() for allowed_model in allowed_models)
    return any(
        model_candidate.startswith(allowed_prefix)
        for model_candidate in model_candidates
        for allowed_prefix in allowed_prefixes
    )


def check_product_access(
    product: str,
    auth_method: str,
    application_id: str | None,
    model: str | None,
    provider: str | None = None,
) -> tuple[bool, str | None]:
    """
    Check if request is authorized for product.
    Returns (allowed, error_message).
    """
    resolved_product = resolve_product_alias(product)
    config = PRODUCTS.get(resolved_product)
    if config is None:
        return False, f"Unknown product: {product}"

    settings = get_settings()
    is_api_key = auth_method == "personal_api_key"
    if is_api_key and not config.allow_api_keys:
        return False, f"Product '{product}' requires OAuth authentication"

    is_oauth = auth_method == "oauth_access_token"
    if is_oauth and not settings.debug:
        # Skip application ID checks in debug mode
        allowed_application_ids = config.allowed_application_ids or frozenset()
        if application_id not in allowed_application_ids:
            return False, f"OAuth application not authorized for product '{product}'"

    if model and config.allowed_models is not None:
        if not _model_matches_product_allowlist(model, config.allowed_models, provider=provider, settings=settings):
            return False, f"Model '{model}' not allowed for product '{product}'"

    return True, None
