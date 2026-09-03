"""Per-run scoped-token minting for sandboxes routed to the Go ai-gateway.

Routed runs authenticate with a short-lived `phe_` token minted here from the worker's
gateway credential: pinned product and on-behalf-of team, per-run spend cap, one internal
wallet. Minting is best-effort and the matching must agree with `resolveGatewayTarget` in
products/desktop/packages/agent/src/utils/gateway.ts; the agent routes to the Go gateway
only when the product is allowlisted AND a token is present, so a mint failure or matcher
disagreement degrades the run to the Python gateway rather than failing it.
"""

import json
import time
import random
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

import requests
from prometheus_client import Counter

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
    "signals_scout": "signals",
    "slack": "slack_app",
    "support_reply": "conversations",
}

# Mirrors SIGNALS_STAGE_PRODUCTS + SCOUT_STAGE_PREFIX in gateway.ts.
_SIGNALS_STAGE_PRODUCTS = frozenset({"scout", "research", "implementation", "repo_selection", "custom_agent"})
_SCOUT_STAGE_PREFIX = "scout:"

_MAX_CAP_USD = Decimal("10000")
_MAX_CAP_DECIMAL_PLACES = 6

# Products whose runs may mint an internally funded token. Mint scope needs
# server-side provenance: `internal` and some origin_product values are
# API-settable, so an unmapped origin marked internal resolves to
# background_agents and must never mint. Signals products qualify because they
# are reachable only through the server-stamped, PATCH-protected ai_stage.
# review_hog qualifies because validate_origin_product reserves the origin and
# the resolver requires the server-stamped `internal` flag; rows predating the
# reservation resolve to posthog_code and cannot mint.
MINTABLE_PRODUCTS = frozenset(
    {
        "review_hog",
        "signals_scout",
        "signals_research",
        "signals_implementation",
        "signals_repo_selection",
        "signals_custom_agent",
    }
)

# Model pins carried on the minted token: the pipeline's stage pins, the
# implicit agent-SDK calls (the haiku small/fast utility model and the sonnet
# generations the explore subagent's bare `sonnet` alias resolves to), and
# every registry-supported reviewer-arm model. Persisted arms resolve against
# the live registry with no re-pin step, and a dispatch denial does not fall
# back to the legacy gateway, so an arm outside the pin would fail its turns
# outright. Gateway-served models (slash-namespaced) stay out: an entry the
# gateway cannot resolve fails the whole mint with a 400. A gateway without
# allowed_models support ignores the field.
_PRODUCT_ALLOWED_MODELS: dict[str, list[str]] = {
    "review_hog": [
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-opus-4-5",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-fable-5",
        "gpt-5",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    ],
}

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


def _token_ttl_seconds() -> int:
    """Token lifetime: the explicit setting, else the run-duration cap plus a settle
    buffer, so a capped run cannot outlive its token (expiry under a live run fails
    every remaining LLM call with no fallback). A disabled run cap derives the 24h
    mint maximum; interactive sessions are cap-exempt and could still outlive it,
    but only capped background products are routed. Clamped to mint bounds (60s..24h).
    """
    configured = int(settings.SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS or 0)
    if configured <= 0:
        run_cap = int(getattr(settings, "TASKS_MAX_RUN_DURATION_SECONDS", 0) or 0)
        configured = run_cap + 3600 if run_cap > 0 else 86400
    return max(60, min(configured, 86400))


def _cap_override(raw: str, key: str, setting_name: str) -> str | None:
    if not raw:
        return None
    try:
        override = json.loads(raw).get(key)
    except (ValueError, AttributeError):
        logger.warning("Ignoring invalid JSON object for %s", setting_name)
        return None
    if override is None:
        return None
    try:
        cap = Decimal(str(override))
    except (InvalidOperation, ValueError):
        logger.warning("Ignoring invalid cap for %s", setting_name)
        return None
    if not cap.is_finite():
        logger.warning("Ignoring invalid cap for %s", setting_name)
        return None
    exponent = cap.as_tuple().exponent
    if not isinstance(exponent, int):
        logger.warning("Ignoring invalid cap for %s", setting_name)
        return None
    decimal_places = max(0, -exponent)
    if cap <= 0 or cap > _MAX_CAP_USD or decimal_places > _MAX_CAP_DECIMAL_PLACES:
        logger.warning("Ignoring invalid cap for %s", setting_name)
        return None
    return f"{cap:f}"


def _token_cap_usd(team_id: int, ai_product: str) -> str:
    """Per-run cap: the product override, else the team override, else the default.

    The product override wins because run cost tracks the kind of work, not who
    it runs for — implementation runs regularly outspend every other stage. The
    team override raises a single team (team 2's custom scouts run hotter than
    the external fleet) without raising everyone's ceiling.
    """
    product_cap = _cap_override(
        settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES, ai_product, "product cap overrides"
    )
    if product_cap is not None:
        return product_cap
    team_cap = _cap_override(settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES, str(team_id), "cap overrides")
    if team_cap is not None:
        return team_cap
    return str(settings.SANDBOX_AI_GATEWAY_TOKEN_CAP_USD)


def mint_scoped_token(*, ai_product: str, team_id: int, user: str | None = None) -> str | None:
    """Mint a `phe_` scoped token pinned to (ai_product, obo=team_id), or None on failure.

    `user` pins the acting identity (the run's distinct id) so routed runs keep
    per-user ledger and budget attribution instead of pooling under the team.
    Retries mint rate limits (429) and transient upstream errors with jittered
    backoff. Callers treat None as "route this run to the Python gateway".
    """
    base_url = (settings.SANDBOX_AI_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")
    mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
    if not base_url or not mint_key:
        return None

    body: dict[str, Any] = {
        "cap_usd": _token_cap_usd(team_id, ai_product),
        "ttl_seconds": _token_ttl_seconds(),
        "product": ai_product,
        "obo": str(team_id),
    }
    if user:
        body["user"] = user
    allowed_models = _PRODUCT_ALLOWED_MODELS.get(ai_product)
    if allowed_models:
        body["allowed_models"] = allowed_models
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
    logger.warning(
        "ai_gateway_token: mint failed, run falls back to the Python gateway",
        extra={"ai_product": ai_product, "team_id": team_id, "error": last_error},
    )
    return None
