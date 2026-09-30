"""Per-run scoped-token minting for sandboxes routed to the Go ai-gateway.

Routed runs authenticate with a short-lived `phe_` token minted here from the worker's
gateway credential: pinned product and on-behalf-of team, per-run spend cap, one internal
wallet. Minting is best-effort and the matching must agree with `resolveGatewayTarget` in
products/desktop/packages/agent/src/utils/gateway.ts; the agent routes to the Go gateway
only when the product is allowlisted AND a token is present, so a mint failure or matcher
disagreement degrades the run to the Python gateway rather than failing it.
"""

import time
import random
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

import requests
from prometheus_client import Counter

from products.tasks.backend.logic.services.desktop_gateway_token import (
    POSTHOG_CODE_PRODUCT,
    PRODUCT_CREDIT_BUCKET,
    _cap_override,
    _team_credit_refusal,
    _valid_cap,
    desktop_rollout_enabled,
    posthog_code_plan,
    valid_caps,
)
from products.tasks.backend.logic.services.gateway_model_pin import (
    FREE_TIER_MODELS,
    PRODUCT_ALLOWED_MODELS,
    model_allowed_by_product_pin,
)
from products.tasks.backend.logic.services.run_actor import is_slack_interaction_state
from products.tasks.backend.logic.services.sandbox_config import MAX_SANDBOX_TTL_SECONDS

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

AI_GATEWAY_TOKEN_MINTS = Counter(
    "tasks_ai_gateway_token_mints_total",
    "Scoped-token mint attempts for gateway-routed sandbox runs",
    labelnames=["result"],
)

# Mirrors resolveGatewayProduct in products/desktop/packages/agent/src/utils/gateway.ts.
_ORIGIN_TO_GATEWAY_PRODUCT: dict[str, str] = {
    "loop": "posthog_code",
    "onboarding": "onboarding",
    "posthog_ai": "posthog_ai",
    "review_hog": "review_hog",
    "scout_suggestions": "signals",
    "signal_report": "signals",
    "signals_chat": "signals",
    "signals_scout": "signals",
    "slack": "slack_app",
    "support_reply": "conversations",
    "workflow": "workflows",
}

# Mirrors SIGNALS_STAGE_PRODUCTS + SCOUT_STAGE_PREFIX in gateway.ts.
_SIGNALS_STAGE_PRODUCTS = frozenset(
    {"scout", "research", "implementation", "repo_selection", "custom_agent", "inbox", "chat", "scout_suggestions"}
)
_SCOUT_STAGE_PREFIX = "scout:"

# Products whose runs may mint an internally funded token. Mint scope needs
# server-side provenance: `internal` and some origin_product values are
# API-settable, so an unmapped origin marked internal resolves to
# background_agents and must never mint. Signals products qualify because their
# stages are set only by server flows: pipeline stages by the flows that start
# them, `inbox` / `chat` by `Task.create_run`. A caller owning a report can reach
# `signals_inbox`, so the per-run cap and the product's daily budget bound those two.
# review_hog qualifies because validate_origin_product reserves the origin and
# the resolver requires the server-stamped `internal` flag; rows predating the
# reservation resolve to posthog_code and mint under its gates. slack_app needs server
# provenance too (has_slack_provenance), older rows included.
# workflows qualifies because validate_origin_product reserves its origin for the
# workflow_tasks endpoint. posthog_ai is API-settable but not internally funded: its token
# bills the run's own team to AI credits, and the mint refuses an exhausted balance.
# posthog_code is the customer's own product: the token bills the run's team, and the rollout
# flag, the plan pin and the credit bucket gate the mint.
MINTABLE_PRODUCTS = frozenset(
    {
        "posthog_ai",
        "posthog_code",
        "review_hog",
        "slack_app",
        "signals_scout",
        "signals_research",
        "signals_implementation",
        "signals_repo_selection",
        "signals_custom_agent",
        "workflows",
        "signals_inbox",
        "signals_chat",
        "signals_scout_suggestions",
    }
)

# Exempt from the background run-duration cap, so their tokens need the longer interactive
# ceiling. Mirrors the stages `Task.create_run` stamps.
INTERACTIVE_MINTABLE_PRODUCTS = frozenset({"signals_inbox", "signals_chat"})

# Interactive and user runs with no wall-clock cap; their tokens last the sandbox lifetime, and
# each new sandbox mints its own token.
SANDBOX_BOUND_MINTABLE_PRODUCTS = frozenset({"posthog_ai", "slack_app", "posthog_code"})

AI_CREDITS_BILLED_PRODUCTS = frozenset(p for p, bucket in PRODUCT_CREDIT_BUCKET.items() if bucket == "ai_credits")

_PRODUCT_ALLOWED_MODELS = PRODUCT_ALLOWED_MODELS

# Minting is optional (no token = Python-gateway fallback), so the total budget
# stays a few seconds: 2 attempts x 3s + one short backoff, not a 30s provisioning stall.
_MINT_ATTEMPTS = 2
_MINT_TIMEOUT_SECONDS = 3


def resolve_sandbox_ai_product(origin_product: str | None, ai_stage: str | None, *, internal: bool = False) -> str:
    """The `ai_product` the agent server will resolve for this run."""
    gateway_product = _ORIGIN_TO_GATEWAY_PRODUCT.get(origin_product or "")
    # Stored rows may carry a caller-set review_hog origin predating its
    # reservation; only the server-stamped `internal` flag admits the mintable product.
    if gateway_product == "review_hog" and not internal:
        logger.warning("review_hog origin without server-stamped internal flag; resolving posthog_code")
        return "posthog_code"
    if gateway_product is None:
        gateway_product = "background_agents" if internal else "posthog_code"
    if gateway_product == "signals" and ai_stage:
        stage = "scout" if ai_stage.startswith(_SCOUT_STAGE_PREFIX) else ai_stage
        if stage in _SIGNALS_STAGE_PRODUCTS:
            return f"signals_{stage}"
    return gateway_product


def sandbox_product_routed(ai_product: str, ai_stage: str | None, products_csv: str) -> bool:
    """Whether the allowlist routes this run to the Go gateway.

    Entries may qualify scouts by skill (`signals_scout:web-analytics`); a plain product
    entry matches every run of that product.
    """
    entries = {entry.strip() for entry in products_csv.split(",") if entry.strip()}
    if ai_product in entries:
        return True
    if ai_stage and ai_stage.startswith(_SCOUT_STAGE_PREFIX):
        skill = ai_stage[len(_SCOUT_STAGE_PREFIX) :]
        return f"{ai_product}:{skill}" in entries
    return False


def is_slack_origin(origin_product: str | None) -> bool:
    """Whether this origin is the reserved one the Slack app's server flows set."""
    return _ORIGIN_TO_GATEWAY_PRODUCT.get(origin_product or "") == "slack_app"


def has_slack_provenance(
    state: dict[str, Any] | None, *, internal: bool = False, prior_slack_run: bool = False
) -> bool:
    """Whether a server flow put this run on the Slack product.

    The API refuses the `slack` origin for client tasks and never writes `internal`, so an internal
    run is server-created. A later run of a Slack task has no stamp, so an earlier stamped run counts.
    """
    return is_slack_interaction_state(state) or internal or prior_slack_run


def model_allowed_by_pin(pin: list[str], model: str | None) -> bool:
    from products.tasks.backend.model_catalog import normalize_model_id  # noqa: PLC0415

    return bool(model) and normalize_model_id(model or "") in {normalize_model_id(entry) for entry in pin}


def _posthog_code_team(team_id: int) -> "Team | None":
    from posthog.models import Team  # noqa: PLC0415

    return Team.objects.select_related("organization").filter(id=team_id).first()


def _posthog_code_refusal(team_id: int, model: str | None) -> str | None:
    """The rollout flag is the switch for the product; a free plan's pin has no model an
    unpinned or paid-model run could fall back to."""
    team = _posthog_code_team(team_id)
    if team is None or not desktop_rollout_enabled(team.organization, team):
        return "not_rolled_out"
    if posthog_code_plan(team) == "free" and not model_allowed_by_pin(FREE_TIER_MODELS, model):
        return "model_outside_pin"
    return None


def posthog_code_allowed_models(team_id: int) -> list[str] | None:
    team = _posthog_code_team(team_id)
    if team is not None and posthog_code_plan(team) == "free":
        return list(FREE_TIER_MODELS)
    return None


def mint_refusal(
    ai_product: str,
    *,
    team_id: int,
    state: dict[str, Any] | None,
    model: str | None,
    runtime: str | None,
    internal: bool = False,
    prior_slack_run: bool = False,
) -> str | None:
    """Why a routed run must not mint; a run without a token stays on the Python gateway."""
    if ai_product == "slack_app" and not has_slack_provenance(
        state, internal=internal, prior_slack_run=prior_slack_run
    ):
        return "no_slack_provenance"
    if ai_product == POSTHOG_CODE_PRODUCT:
        refusal = _posthog_code_refusal(team_id, model)
        if refusal:
            return refusal
    # The Pi harness reads only LLM_GATEWAY_URL.
    if runtime == "pi":
        return "pi_runtime"
    # The gateway denies an off-pin model with no fallback.
    if not model_allowed_by_product_pin(ai_product, model):
        return "model_outside_pin"
    bucket = PRODUCT_CREDIT_BUCKET.get(ai_product)
    if bucket is None:
        return None
    # An unknown balance is no licence to spend.
    try:
        return _team_credit_refusal(team_id, bucket)
    except Exception:
        logger.warning(
            "ai_gateway_token: credit lookup failed, run stays on the Python gateway",
            extra={"team_id": team_id, "bucket": bucket},
            exc_info=True,
        )
        return f"{bucket}_unknown"


def _token_ttl_seconds(ai_product: str) -> int:
    """Token lifetime: the explicit setting, else this product's own run-duration cap plus a
    settle buffer, so a capped run cannot outlive its token (expiry under a live run fails
    every remaining LLM call with no fallback). Only interactive products are exempt from
    the background cap, so only they derive a longer ceiling; giving every token the longest
    one would widen the window on a leaked background token for no run that could use it.
    A disabled cap derives the 24h mint maximum. Clamped to mint bounds (60s..24h).
    """
    configured = int(settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS or 0)
    if configured <= 0:
        if ai_product in SANDBOX_BOUND_MINTABLE_PRODUCTS:
            run_cap = MAX_SANDBOX_TTL_SECONDS
        elif ai_product in INTERACTIVE_MINTABLE_PRODUCTS:
            # These runs are exempt from the background cap, so their own ceiling is the only
            # one that bounds them; zero means unbounded and derives the mint maximum.
            run_cap = int(getattr(settings, "TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS", 0) or 0)
        else:
            run_cap = int(getattr(settings, "TASKS_MAX_RUN_DURATION_SECONDS", 0) or 0)
        configured = run_cap + 3600 if run_cap > 0 else 86400
    return max(60, min(configured, 86400))


def token_cap_usd(team_id: int, ai_product: str) -> str:
    """Per-run cap: the product override, else the team override, else the default.

    The product override wins because run cost tracks the kind of work, not who
    it runs for — implementation runs regularly outspend every other stage. The
    team override raises a single team (team 2's custom scouts run hotter than
    the external fleet) without raising everyone's ceiling.
    """
    # An invalid env entry is dropped and reported, so the product keeps its code default.
    product_cap = valid_caps(settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES, "product cap overrides").get(
        ai_product
    )
    if product_cap is None and ai_product in settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_DEFAULTS:
        product_cap = _valid_cap(
            settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_DEFAULTS[ai_product], "product cap defaults"
        )
    if product_cap is not None:
        return product_cap
    team_cap = _cap_override(settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES, str(team_id), "cap overrides")
    if team_cap is not None:
        return team_cap
    return str(settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD)


def mint_scoped_token(
    *, ai_product: str, team_id: int, user: str | None = None, allowed_models: list[str] | None = None
) -> str | None:
    """Mint a `phe_` scoped token pinned to (ai_product, obo=team_id), or None on failure.

    `user` pins the acting identity (the run's distinct id) so routed runs keep
    per-user ledger and budget attribution instead of pooling under the team.
    `allowed_models` narrows the product's pin (a free Desktop plan).
    Retries mint rate limits (429) and transient upstream errors with jittered
    backoff. Callers treat None as "route this run to the Python gateway".
    """
    base_url = (settings.SANDBOX_AI_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")
    mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
    if not base_url or not mint_key:
        return None

    body: dict[str, Any] = {
        "cap_usd": token_cap_usd(team_id, ai_product),
        "ttl_seconds": _token_ttl_seconds(ai_product),
        "product": ai_product,
        "obo": str(team_id),
    }
    if user:
        body["user"] = user
    pin = allowed_models if allowed_models is not None else _PRODUCT_ALLOWED_MODELS.get(ai_product)
    if pin:
        body["allowed_models"] = pin
    last_error: str = ""
    for attempt in range(_MINT_ATTEMPTS):
        try:
            response = requests.post(
                f"{base_url}/v1/tokens",
                json=body,
                headers={"Authorization": f"Bearer {mint_key}"},
                timeout=_MINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            last_error = str(e)
        else:
            if 200 <= response.status_code < 300:
                try:
                    token = response.json().get("token")
                    last_error = "mint response had no token"
                except (ValueError, AttributeError):
                    token = None
                    last_error = "mint response was not a JSON object"
                if token:
                    AI_GATEWAY_TOKEN_MINTS.labels(result="ok").inc()
                    return token
            elif response.status_code in (429,) or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
            else:
                # 4xx other than 429 will not improve on retry (bad credential, bad body).
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                break
        if attempt < _MINT_ATTEMPTS - 1:
            time.sleep((0.5 * 2**attempt) + random.uniform(0, 0.25))

    AI_GATEWAY_TOKEN_MINTS.labels(result="error").inc()
    # The deploy's log formatter drops `extra`, so the message carries the fields.
    # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs product, team id and the mint error, never the token or mint key
    logger.warning(
        "ai_gateway_token: mint failed, run falls back to the Python gateway (ai_product=%s team_id=%s error=%s)",
        ai_product,
        team_id,
        last_error,
        extra={"ai_product": ai_product, "team_id": team_id, "error": last_error},
    )
    return None
