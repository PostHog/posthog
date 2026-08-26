from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fastapi import HTTPException

from llm_gateway.baseten import BASETEN_DEEPSEEK_PUBLIC_MODEL, BASETEN_GLM53_PUBLIC_MODEL
from llm_gateway.bedrock import BEDROCK_MODEL_IDS, get_bedrock_model_access_candidates, get_bedrock_region_name
from llm_gateway.config import get_settings


class CreditBucket(StrEnum):
    """Customer credit bucket a product's generations bill into.

    Values match (or, once created, will match) the Django quota resource keys
    (ee/billing/quota_limiting.py QuotaResource), which is what the gateway's
    quota resolver checks against. Both buckets have gateway-side quota
    enforcement: an exhausted bucket blocks every caller of the product, the
    same population the usage reporter counts into it.
    """

    AI_CREDITS = "ai_credits"
    POSTHOG_CODE_CREDITS = "posthog_code_credits"


@dataclass(frozen=True)
class ProductConfig:
    # Empty set (the default) or None means no OAuth application is authorized for this product.
    # To permit OAuth access, explicitly list the allowed application IDs.
    allowed_application_ids: frozenset[str] | None = frozenset()
    allowed_models: frozenset[str] | None = None  # None = all allowed
    # True = exact allowlist match, not startswith
    exact_model_match: bool = False
    allow_api_keys: bool = True
    # Which customer credit bucket this product bills into. None = not billed: emitted
    # $ai_generation events are tagged $ai_billable=false and the usage reporter
    # (posthog/tasks/usage_report.py) ignores them. A bucket value tags events billable
    # so the reporter rolls them into that bucket's credit counter, and every caller
    # is blocked when the bucket's quota is exhausted.
    credit_bucket: CreditBucket | None = None
    # When True, OAuth callers must present a server-minted credential (a token carrying
    # the internal `internal_run:read` scope). Set on the internal products that share the
    # PostHog Desktop OAuth app but are only ever driven by sandbox runs — a user's own Code
    # OAuth token can't carry an internal scope, so this stops it routing around the
    # posthog_code free-tier model gate through these products. Personal API keys are
    # unaffected (they reach the gateway only with an explicit, feature-gated
    # llm_gateway:read scope, not the wildcard a consent token uses).
    requires_server_credential: bool = False


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
SIGNALS_US_APP_ID = "01a01611-1dc2-0000-61ea-c4c8322e8936"
SIGNALS_EU_APP_ID = "01a01613-c382-0000-1472-f7881db30f4f"
SIGNALS_DEV_APP_ID = "019fb2ee-9d54-0000-61d9-faf825230d44"

# Shared by `posthog_code` and `slack_app` — the agent that runs in the sandbox
# is the same code regardless of where the task was initiated, so the model
# allowlist is identical.
_POSTHOG_CODE_AGENT_MODELS: Final[frozenset[str]] = frozenset(
    {
        "claude-fable-5",
        "claude-opus-4-5",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.2",
        "gpt-5-mini",
        "@cf/zai-org/glm-5.2",
        "zai-org/glm-5.3",
        "moonshotai/kimi-k3",
    }
)

# Models reserved for specific products must stay restricted even when a product otherwise allows
# every model (`allowed_models=None`). This is an authorization boundary, not merely a
# model-registry advertising filter; the registry also derives its advertising from it so the two
# can't drift. Keys must be lowercase.
RESTRICTED_MODEL_PRODUCTS: Final[dict[str, frozenset[str]]] = {
    # Evaluated by ReviewHog; exposed in PostHog Code behind the posthog-code-deepseek-model flag.
    BASETEN_DEEPSEEK_PUBLIC_MODEL: frozenset({"posthog_code", "review_hog"}),
    BASETEN_GLM53_PUBLIC_MODEL: frozenset({"posthog_code", "review_hog"}),
}

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
        allowed_models=_POSTHOG_CODE_AGENT_MODELS | {BASETEN_DEEPSEEK_PUBLIC_MODEL} | BEDROCK_MODELS,
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
                "claude-fable-5",
                "claude-opus-4-5",
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-opus-4-8",
                "claude-opus-5",
                "claude-sonnet-4-5",
                "claude-sonnet-5",
                "claude-haiku-4-5",
                "gpt-5.4",
                "gpt-5.3-codex",
                "gpt-5.2",
                "gpt-5-mini",
                "gpt-5.6-luna",
                # ReviewHog sandbox runs route here (no review_hog entry in the agent's
                # origin→product map), so its reviewer-experiment arms must be allowed.
                "gpt-5.6-sol",
            }
            | BEDROCK_MODELS
        ),
        allow_api_keys=False,
        credit_bucket=None,
        requires_server_credential=True,
    ),
    # The setup wizard's cloud run (Task.OriginProduct.ONBOARDING). Unbilled like
    # background_agents, and this one runs before the user has decided to buy anything.
    # Two gates keep the free route shut: Django refuses `onboarding` as a caller-supplied
    # task origin, and the agent-server only routes here for a run carrying the protected
    # `wizard_config` state key. Models stay narrow because a free bucket shouldn't reach
    # the whole fleet; claude-opus-4-8 is only the SDK's fallback for the pinned sonnet.
    "onboarding": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=frozenset({"claude-sonnet-5", "claude-opus-4-8"}) | BEDROCK_MODELS,
        allow_api_keys=False,
        credit_bucket=None,
        requires_server_credential=True,
    ),
    "slack_app": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=_POSTHOG_CODE_AGENT_MODELS | BEDROCK_MODELS,
        allow_api_keys=False,
        credit_bucket=CreditBucket.AI_CREDITS,
        requires_server_credential=True,
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
        allowed_models=frozenset({"claude-haiku-4-5", "gpt-5.6-luna"}),
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
        # Only the dedicated Signals app: dropping the PostHog Code ids is what finally makes
        # this product unreachable from a Desktop-app token.
        allowed_application_ids=frozenset({SIGNALS_US_APP_ID, SIGNALS_EU_APP_ID, SIGNALS_DEV_APP_ID}),
        allowed_models=None,  # any model — the signals pipeline picks models per stage (haiku, sonnet, ...)
        allow_api_keys=True,
        credit_bucket=None,
        requires_server_credential=True,
    ),
    "review_hog": ProductConfig(
        allowed_application_ids=None,
        # The models the review pipeline pins: sonnet-5 (perspectives + one-shots), opus-4-8
        # (validation), opus-5 (outcome judge), gpt-5.5 / gpt-5.6 sol+luna+terra (Codex reviewers),
        # GLM 5.2/5.3 and DeepSeek V4 Flash (evaluated as reviewers).
        allowed_models=frozenset(
            {
                "@cf/zai-org/glm-5.2",
                "zai-org/glm-5.3",
                "deepseek-ai/deepseek-v4-flash-0731",
                "claude-sonnet-5",
                "claude-opus-4-8",
                "claude-opus-5",
                "gpt-5.5",
                "gpt-5.6-sol",
                "gpt-5.6-luna",
                "gpt-5.6-terra",
            }
        ),
        allow_api_keys=True,
        # Deliberately unbilled while ReviewHog is an internal alpha.
        credit_bucket=None,
    ),
    # Server-side security review before a custom sandbox image is built. The Django worker mints a
    # short-lived OAuth token carrying the internal provenance marker; personal API keys and normal
    # Code OAuth tokens cannot spend this unbilled product's budget.
    "custom_image_scans": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=frozenset({"@cf/zai-org/glm-5.2"}),
        allow_api_keys=False,
        credit_bucket=None,
        requires_server_credential=True,
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
        requires_server_credential=True,
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
    "web_analytics": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"claude-haiku-4-5"}),
        allow_api_keys=True,
        credit_bucket=None,
    ),
    # changelog-bot. Exact-pinned to these two ids (the agent sends "openai/"-prefixed).
    "changelog_bot": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"openai/gpt-5.6-terra", "openai/gpt-5.6-sol"}),
        exact_model_match=True,
        allow_api_keys=True,
        credit_bucket=None,
    ),
    # Stamphog: the sandboxed PR reviewer (Sonnet, OAuth-only in practice) and the daily merged-PR
    # digest summarization (Haiku, server-side via the shared key). Low volume, internal infra.
    # The reviewer runs inside a sandbox over untrusted PR content, so it authenticates with a
    # short-lived server-minted OAuth token under the shared sandbox app — hence the app allowlist.
    # allow_api_keys stays True only for the digest's server-side calls (the shared key never
    # enters a sandbox); it can flip off once the digest mints tokens too.
    # Deliberately unbilled, same posture as review_hog/conversations: reviews and digests are work
    # done by PostHog, not customer-billable usage, and the worker attributes spend per customer team
    # via the team_id header — a credit_bucket here would silently charge customer AI credits for it.
    # The trade-off (any personal API key can reach an unbilled route) is shared by every
    # key-accessible unbilled product in this table and is bounded by the model pins.
    # requires_server_credential closes the OAuth side of that class: reviewer tokens are minted
    # server-side with the internal marker, so a user's own Desktop OAuth token can't ride this route
    # around the posthog_code free-tier gate.
    "stamphog": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID, POSTHOG_CODE_DEV_APP_ID}),
        allowed_models=frozenset({"claude-haiku-4-5", "claude-sonnet-5"}),
        allow_api_keys=True,
        credit_bucket=None,
        requires_server_credential=True,
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
    exact: bool = False,
) -> bool:
    model_candidates = {model.lower()}
    if provider == "bedrock":
        model_candidates = set(
            get_bedrock_model_access_candidates(model, region_name=get_bedrock_region_name(settings=settings))
        )

    allowed_lower = tuple(allowed_model.lower() for allowed_model in allowed_models)
    if exact:
        # A variant like "<pinned>-pro" is a distinct, pricier model — reject it.
        return any(candidate in allowed_lower for candidate in model_candidates)
    # Default: prefix match, so Bedrock/agent ids with region+version suffixes
    # (e.g. "claude-3-5-sonnet-20241022-v2:0") match a short pinned name.
    return any(
        model_candidate.startswith(allowed_prefix)
        for model_candidate in model_candidates
        for allowed_prefix in allowed_lower
    )


FREE_TIER_RESTRICTION_REASON: Final[str] = "paid_plan_required"

# Internal scope stamped on every server-minted sandbox/agent token (see INTERNAL_SCOPES in
# posthog/temporal/oauth.py). Being an internal scope, it can't be obtained through the OAuth
# consent flow or a personal API key, so its presence proves a token was minted server-side
# rather than held by a user. Products with requires_server_credential demand it from OAuth callers.
INTERNAL_RUN_SCOPE: Final[str] = "internal_run:read"

# Narrower marker on the same tokens: the run was started by a person, not by one of our
# schedulers (INTERACTIVE_RUN_SCOPE in posthog/temporal/oauth.py). Also an internal scope, so
# it can't be self-granted. Used to pick the budget, never to grant access.
INTERACTIVE_RUN_SCOPE: Final[str] = "interactive_run:read"

# Not a product: no caller can declare it, and it never appears in PRODUCTS. It only names a
# budget in product_cost_limits / user_cost_limits, resolved from the token by resolve_cost_key.
SIGNALS_INTERACTIVE_COST_KEY: Final[str] = "signals_interactive"


def check_free_tier_model_access(
    product: str,
    model: str | None,
    provider: str | None,
    code_usage_billed: bool,
    usage_unlimited: bool,
) -> tuple[bool, str | None]:
    if resolve_product_alias(product) != "posthog_code":
        return True, None
    # model=None is safe: every route requires a model at validation, so the request 422s
    if code_usage_billed or usage_unlimited or model is None:
        return True, None

    settings = get_settings()
    free_models = frozenset(settings.posthog_code_free_tier_models)
    if _model_matches_product_allowlist(model, free_models, provider=provider, settings=settings):
        return True, None

    available = ", ".join(sorted(free_models))
    return False, (
        f"Model '{model}' needs a paid PostHog plan. Models available on the free tier: {available}. "
        "Add a payment method to your organization to unlock all models."
    )


# Models a caller may only select while the paired flag is enabled for them, mirroring
# products/tasks MODEL_ACCESS_FLAGS. Each model maps to its own access flag — the same flag the
# Desktop picker gates it behind — so an entitlement can't be widened for one model by proxy of
# another. Keys are the model ids callers send.
MODEL_ACCESS_FLAGS: Final[dict[str, str]] = {
    "moonshotai/kimi-k3": "tasks-kimi-k3",
    "deepseek-ai/deepseek-v4-flash-0731": "posthog-code-deepseek-model",
    "zai-org/glm-5.3": "posthog-code-glm-53-model",
}


def get_required_model_flag(model: str | None) -> str | None:
    """The feature flag a caller needs to select `model`, or None when it is generally available."""
    if not model:
        return None
    normalized = model.strip().lower()
    for gated_model, flag_key in MODEL_ACCESS_FLAGS.items():
        if gated_model.lower() == normalized:
            return flag_key
    return None


def filter_to_free_tier_models(model_ids: list[str]) -> list[str]:
    """Subset of model_ids on the posthog_code free tier."""
    settings = get_settings()
    free_models = frozenset(settings.posthog_code_free_tier_models)
    return [m for m in model_ids if _model_matches_product_allowlist(m, free_models, settings=settings)]


def is_model_restricted_for_product(model: str, product: str) -> bool:
    """Whether `model` is reserved for other products — see RESTRICTED_MODEL_PRODUCTS."""
    allowed_products = RESTRICTED_MODEL_PRODUCTS.get(model.strip().lower())
    return allowed_products is not None and resolve_product_alias(product) not in allowed_products


def resolve_cost_key(product: str, scopes: list[str] | None) -> str:
    """The budget a request meters against, which is not always its product.

    Signals runs a scheduled pipeline and a set of buttons in the Inbox through one product.
    Their volume has different owners — ours and the customer's — so they get separate budgets,
    resolved from the token's own provenance marker rather than from the product the caller
    declared, which a sandbox is free to choose.

    The marker decides alone, without also requiring the declared product to be `signals`: a run
    whose token still comes from the Array app (the fallback while a region has no Signals app
    row) can declare `posthog_code` or `background_agents` instead, and pairing the two would let
    that choice move the run off the interactive budget and out of the per-run spend ceiling.
    Only interactive Signals runs are ever minted with the scope, so keying on it is sufficient.
    """
    if INTERACTIVE_RUN_SCOPE in (scopes or []):
        return SIGNALS_INTERACTIVE_COST_KEY
    return resolve_product_alias(product)


def check_product_access(
    product: str,
    auth_method: str,
    application_id: str | None,
    model: str | None,
    provider: str | None = None,
    scopes: list[str] | None = None,
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
        if application_id not in (config.allowed_application_ids or frozenset()):
            return False, f"OAuth application not authorized for product '{product}'"

    # Internal products that share the PostHog Desktop OAuth app are only ever driven by
    # server-minted sandbox tokens; a user's own Desktop OAuth token would otherwise reach them
    # and route around the posthog_code free-tier model gate. Require the internal marker that
    # only server-minted tokens carry. OAuth-only: personal API keys reach the gateway with an
    # explicit, feature-gated llm_gateway:read scope (a `*` PAK is rejected at auth), so the
    # shared server-side gateway key still works here.
    if config.requires_server_credential and is_oauth and INTERNAL_RUN_SCOPE not in (scopes or []):
        return False, f"Product '{product}' requires a server-minted credential"

    if model and is_model_restricted_for_product(model, resolved_product):
        return False, f"Model '{model}' not allowed for product '{product}'"

    if model and config.allowed_models is not None:
        if not _model_matches_product_allowlist(
            model, config.allowed_models, provider=provider, settings=settings, exact=config.exact_model_match
        ):
            return False, f"Model '{model}' not allowed for product '{product}'"

    return True, None
