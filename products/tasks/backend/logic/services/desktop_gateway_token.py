"""PostHog Desktop (`posthog_code`) tokens on the Go ai-gateway.

Shared by the desktop app's mint endpoint and the sandbox worker's mint, so it stays free of
Temporal imports.
"""

import json
import logging
import functools
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from django.conf import settings

import requests
import posthoganalytics
from prometheus_client import Counter

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false

from products.tasks.backend.logic.services.gateway_model_pin import DESKTOP_AGENT_MODELS, FREE_TIER_MODELS

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

POSTHOG_CODE_PRODUCT = "posthog_code"

# Mirrors PRODUCTS[*].credit_bucket in services/llm-gateway/src/llm_gateway/products/config.py.
# Both gateways refuse an exhausted bucket, and a mint checks it first so a capped or deactivated
# org never gets a token.
PRODUCT_CREDIT_BUCKET: dict[str, str] = {
    "posthog_ai": "ai_credits",
    "posthog_code": "posthog_code_credits",
    "slack_app": "ai_credits",
    "workflows": "ai_credits",
}

# The legacy gateway's refusal for an exhausted Desktop bucket; the app matches on it.
POSTHOG_CODE_CREDITS_EXHAUSTED_DETAIL = (
    "Your team has reached its PostHog Desktop usage limit for this billing period. "
    "See https://app.posthog.com/organization/billing for your usage and limits."
)
CREDIT_BUCKET_EXHAUSTED_DENIAL = "credit_bucket_exhausted:posthog_code_credits"

_MAX_CAP_USD = Decimal("10000")
_MAX_CAP_DECIMAL_PLACES = 6

_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 86400

# One attempt on the web request path: the app falls back to the legacy gateway and retries later,
# so a slow gateway must not hold the worker.
_MINT_TIMEOUT_SECONDS = 3

PosthogCodePlan = Literal["paid", "free"]

DESKTOP_GATEWAY_MINTS = Counter(
    "posthog_desktop_gateway_token_mints_total",
    "PostHog Desktop gateway token mints, by outcome (ok/rate_limited/refused/unreachable/malformed)",
    labelnames=["outcome"],
)


def _team_credit_refusal(team_id: int, bucket: str) -> str | None:
    from posthog.models import Team  # noqa: PLC0415

    from ee.billing.quota_limiting import QuotaResource, is_team_over_credit_budget  # noqa: PLC0415

    row = Team.objects.filter(id=team_id).values_list("api_token", "organization__is_active").first()
    if not row:
        return None
    api_token, org_active = row
    if org_active is False:
        return "org_deactivated"
    if api_token and is_team_over_credit_budget(api_token, QuotaResource(bucket)):
        return f"{bucket}_exhausted"
    return None


def _report_invalid_caps(setting_name: str, problem: str) -> None:
    logger.warning("Ignoring invalid cap setting %s: %s", setting_name, problem)
    # The mint path calls this, so keep the request's locals out of the capture.
    with posthoganalytics.new_context():
        posthoganalytics.set_capture_exception_code_variables_context(False)
        capture_exception(ValueError(f"{setting_name} {problem}"), {"setting": setting_name})


def _valid_cap(value: object, setting_name: str) -> str | None:
    try:
        cap = Decimal(str(value))
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


@functools.lru_cache(maxsize=32)
def valid_caps(raw: str, setting_name: str) -> Mapping[str, str]:
    """Parsed once per value per process. A malformed map or entry is captured, because every mint
    would otherwise fall back to a default in silence."""
    if not raw:
        return MappingProxyType({})
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        _report_invalid_caps(setting_name, "is not a JSON object")
        return MappingProxyType({})
    caps: dict[str, str] = {}
    invalid: list[str] = []
    for key, value in parsed.items():
        cap = _valid_cap(value, setting_name)
        if cap is None:
            invalid.append(str(key))
        else:
            caps[str(key)] = cap
    if invalid:
        _report_invalid_caps(setting_name, f"has invalid entries for {sorted(invalid)}")
    return MappingProxyType(caps)


def _cap_override(raw: str, key: str, setting_name: str) -> str | None:
    return valid_caps(raw, setting_name).get(key)


def posthog_code_plan(team: "Team") -> PosthogCodePlan:
    """`paid` when the org is active and billing grants Desktop usage; the rule `quota_limits` reports."""
    organization = team.organization
    if organization.is_active is not False and organization.is_feature_available(AvailableFeature.POSTHOG_CODE_USAGE):
        return "paid"
    return "free"


def plan_allowed_models(plan: PosthogCodePlan) -> list[str]:
    return list(DESKTOP_AGENT_MODELS) if plan == "paid" else list(FREE_TIER_MODELS)


def desktop_rollout_enabled(organization: "Organization", team: "Team", distinct_id: str | None = None) -> bool:
    """The rollout flag, targeted on the org. A flag outage reads as off, which keeps both legs on legacy."""
    organization_id = str(organization.id)
    try:
        return feature_enabled_or_false(
            settings.DESKTOP_GATEWAY_ROLLOUT_FLAG,
            distinct_id or organization_id,
            groups={"organization": organization_id, "project": str(team.id)},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("desktop_gateway_token: rollout flag unavailable, treating as off", exc_info=True)
        return False


class DesktopGatewayMintError(Exception):
    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


def desktop_gateway_configured() -> bool:
    return bool(settings.DESKTOP_GATEWAY_URL and settings.DESKTOP_GATEWAY_MINT_KEY)


def desktop_gateway_base_url() -> str:
    return (settings.DESKTOP_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")


@functools.lru_cache(maxsize=8)
def _valid_default_cap(raw: str, setting_name: str) -> str | None:
    cap = _valid_cap(raw, setting_name)
    if cap is None:
        _report_invalid_caps(setting_name, "is not a valid cap")
    return cap


def desktop_token_cap_usd(team_id: int) -> str:
    team_cap = _cap_override(
        settings.DESKTOP_GATEWAY_TOKEN_CAP_USD_OVERRIDES, str(team_id), "desktop token cap overrides"
    )
    if team_cap is not None:
        return team_cap
    return _valid_default_cap(settings.DESKTOP_GATEWAY_TOKEN_CAP_USD, "desktop token cap") or "200"


def desktop_token_ttl_seconds() -> int:
    return max(_MIN_TTL_SECONDS, min(int(settings.DESKTOP_GATEWAY_TOKEN_TTL_SECONDS), _MAX_TTL_SECONDS))


def mint_desktop_gateway_token(*, team_id: int, user: str, allowed_models: list[str]) -> dict[str, Any]:
    """Mint one session token; returns Go's body. Raises DesktopGatewayMintError on any refusal or
    transport failure; the bearer never appears in logs or exception text."""
    body = {
        "cap_usd": desktop_token_cap_usd(team_id),
        "ttl_seconds": desktop_token_ttl_seconds(),
        "product": POSTHOG_CODE_PRODUCT,
        "obo": str(team_id),
        "user": user,
        "allowed_models": allowed_models,
    }
    try:
        response = requests.post(
            f"{desktop_gateway_base_url()}/v1/tokens",
            json=body,
            headers={"Authorization": f"Bearer {settings.DESKTOP_GATEWAY_MINT_KEY}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        DESKTOP_GATEWAY_MINTS.labels(outcome="unreachable").inc()
        logger.warning("desktop gateway mint: transport failure (%s)", type(e).__name__)
        raise DesktopGatewayMintError("gateway unreachable") from e

    if response.status_code == 429:
        # The mint key's per-minute ceiling (see DESKTOP_GATEWAY_TOKEN_TTL_SECONDS), shared by every user.
        DESKTOP_GATEWAY_MINTS.labels(outcome="rate_limited").inc()
        logger.warning("desktop_gateway_token: mint rate limited by the gateway (status=429)")
        raise DesktopGatewayMintError("mint rate limited with HTTP 429", rate_limited=True)
    if response.status_code != 201:
        DESKTOP_GATEWAY_MINTS.labels(outcome="refused").inc()
        logger.warning("desktop gateway mint: refused (status=%s)", response.status_code)
        raise DesktopGatewayMintError(f"mint refused with HTTP {response.status_code}")
    try:
        minted = response.json()
    except ValueError as e:
        DESKTOP_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise DesktopGatewayMintError("mint response was not JSON") from e
    if not isinstance(minted, dict) or not minted.get("token") or not minted.get("expires_at"):
        DESKTOP_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise DesktopGatewayMintError("mint response missing token or expires_at")
    DESKTOP_GATEWAY_MINTS.labels(outcome="ok").inc()
    return minted
