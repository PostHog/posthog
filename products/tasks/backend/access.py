import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache

import structlog
import posthoganalytics
from posthoganalytics.types import FeatureFlagResult

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false, get_feature_flag_or_none

from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.logic.services.desktop_gateway_token import best_customer_trust_score
from products.tasks.backend.metrics import (
    DesktopAccessOutcome,
    observe_desktop_access_decision,
    observe_desktop_access_flag_unresolved,
)

from ee.billing.billing_manager import (
    BillingManager,
    FundingStatusUnavailable,
    OrganizationFundingStatus,
    PrepaidCreditState,
)

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

DESKTOP_ACCESS_OVERRIDE_FLAG = "posthog-desktop-access-override"
DESKTOP_SIGNUP_GATE_FLAG = "posthog-desktop-signup-gate"
_FUNDING_DECISION_CACHE_KEY = "desktop_access_funding_decision:{organization_id}"


class DesktopAccessResolutionError(Exception):
    pass


class DesktopAccessDecision(StrEnum):
    ALLOWED = "allowed"
    STARTUP_PLAN = "startup_plan"
    PREPAID_CREDITS = "prepaid_credits"
    SIGNUPS_PAUSED = "signups_paused"

    @property
    def allowed(self) -> bool:
        return self == self.ALLOWED

    @property
    def reason(self) -> DesktopAccessReason | None:
        if self == self.STARTUP_PLAN:
            return DesktopAccessReason.STARTUP_PLAN
        if self == self.PREPAID_CREDITS:
            return DesktopAccessReason.PREPAID_CREDITS
        return None


def _get_funding_status(user: User, organization: "Organization") -> OrganizationFundingStatus:
    try:
        return BillingManager(get_cached_instance_license(), user).get_funding_status(organization)
    except FundingStatusUnavailable as error:
        raise DesktopAccessResolutionError("Could not resolve organization funding status") from error


_DECISION_OUTCOMES: dict[DesktopAccessDecision, DesktopAccessOutcome] = {
    DesktopAccessDecision.ALLOWED: "allowed",
    DesktopAccessDecision.STARTUP_PLAN: "startup_plan",
    DesktopAccessDecision.PREPAID_CREDITS: "prepaid_credits",
    DesktopAccessDecision.SIGNUPS_PAUSED: "signups_paused",
}


_DECISION_VALUES = frozenset(decision.value for decision in DesktopAccessDecision)


def _signup_cutoff() -> datetime | None:
    raw_cutoff = settings.DESKTOP_SIGNUP_CUTOFF
    if not raw_cutoff:
        return None
    try:
        cutoff = datetime.fromisoformat(raw_cutoff)
    except ValueError as error:
        raise DesktopAccessResolutionError("DESKTOP_SIGNUP_CUTOFF is not an ISO 8601 datetime") from error
    return cutoff if cutoff.tzinfo is not None else cutoff.replace(tzinfo=UTC)


def _signed_up_after_cutoff(user: User) -> bool:
    cutoff = _signup_cutoff()
    return cutoff is not None and user.date_joined >= cutoff


def _resolve_flag(flag_key: str, user: User, organization: "Organization") -> bool | None:
    organization_id = str(organization.id)
    enabled = get_feature_flag_or_none(
        flag_key,
        str(user.distinct_id),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    return enabled if isinstance(enabled, bool) else None


def _flag_enabled(flag_key: str, user: User, organization: "Organization") -> bool:
    enabled = _resolve_flag(flag_key, user, organization)
    if enabled is None:
        raise DesktopAccessResolutionError(f"Could not evaluate the {flag_key} flag")
    return enabled


def _override_enabled(user: User, organization: "Organization") -> bool:
    enabled = _resolve_flag(DESKTOP_ACCESS_OVERRIDE_FLAG, user, organization)
    if enabled is None:
        logger.warning(
            "desktop_access_override_unresolved",
            flag_key=DESKTOP_ACCESS_OVERRIDE_FLAG,
            organization_id=str(organization.id),
        )
        observe_desktop_access_flag_unresolved(flag=DESKTOP_ACCESS_OVERRIDE_FLAG)
        return False
    return enabled


def _funding_decision(user: User, organization: "Organization") -> DesktopAccessDecision:
    funding_status = _get_funding_status(user, organization)
    if funding_status.startup_program_label is not None:
        return DesktopAccessDecision.STARTUP_PLAN
    if funding_status.prepaid_credit_state in {PrepaidCreditState.PENDING, PrepaidCreditState.ACTIVE}:
        return DesktopAccessDecision.PREPAID_CREDITS
    return DesktopAccessDecision.ALLOWED


def _cached_funding_decision(user: User, organization: "Organization", cache_seconds: int) -> DesktopAccessDecision:
    """A cache error falls through to the live lookup; a resolution failure is never cached."""
    cache_key = _FUNDING_DECISION_CACHE_KEY.format(organization_id=organization.id)
    try:
        cached = cache.get(cache_key)
    except Exception:
        logger.warning("desktop_access_decision_cache_read_failed", exc_info=True)
        cached = None
    if isinstance(cached, str) and cached in _DECISION_VALUES:
        return DesktopAccessDecision(cached)
    decision = _funding_decision(user, organization)
    try:
        cache.set(cache_key, decision.value, timeout=cache_seconds)
    except Exception:
        logger.warning("desktop_access_decision_cache_write_failed", exc_info=True)
    return decision


def get_desktop_access_decision(
    user: User, organization: "Organization", *, funding_cache_seconds: int = 0
) -> DesktopAccessDecision:
    """`funding_cache_seconds` caches the billing funding lookup per org; the per-user override
    flag is evaluated on every call."""
    if not user or not user.is_authenticated or not user.distinct_id:
        raise DesktopAccessResolutionError("Authentication is required to evaluate Desktop access")

    if settings.DEBUG:
        observe_desktop_access_decision(outcome="override")
        return DesktopAccessDecision.ALLOWED

    try:
        if _override_enabled(user, organization):
            observe_desktop_access_decision(outcome="override")
            return DesktopAccessDecision.ALLOWED
        # The gate flag is evaluated only for users past the cutoff, so existing users pay no extra flag call.
        if _signed_up_after_cutoff(user) and _flag_enabled(DESKTOP_SIGNUP_GATE_FLAG, user, organization):
            decision = DesktopAccessDecision.SIGNUPS_PAUSED
        elif funding_cache_seconds > 0:
            decision = _cached_funding_decision(user, organization, funding_cache_seconds)
        else:
            decision = _funding_decision(user, organization)
    except DesktopAccessResolutionError:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise

    observe_desktop_access_decision(outcome=_DECISION_OUTCOMES[decision])
    return decision


class PostHogAIAccessDecision(StrEnum):
    """Whether a user gets PostHog AI 2.0 (the sandbox runtime). The value is an internal reason code."""

    GRANDFATHERED = "grandfathered"
    ALLOWED = "allowed"
    BETA_OFF = "beta_off"
    STARTUP_PROGRAM = "startup_program"
    PREPAID_CREDITS = "prepaid_credits"
    CREATED_AFTER_CUTOFF = "created_after_cutoff"
    LOW_TRUST = "low_trust"
    UNRESOLVED = "unresolved"

    @property
    def allowed(self) -> bool:
        return self in (PostHogAIAccessDecision.GRANDFATHERED, PostHogAIAccessDecision.ALLOWED)


# Everyone who has PostHog AI 2.0 before the gate keeps it, whatever the beta rules say.
POSTHOG_AI_GRANDFATHERED_FLAGS = ("phai-sandbox-mode", "tasks")
POSTHOG_AI_BETA_FLAG = "phai-2-beta"
_POSTHOG_AI_FUNDING_CACHE_SECONDS = 300


@frozen
class PostHogAIBetaRules:
    created_before: datetime
    min_trust_score: float


def _posthog_ai_beta_rules(payload: object) -> PostHogAIBetaRules | None:
    """Reads the beta rules from the flag payload, so they change without a deploy."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    try:
        cutoff = datetime.fromisoformat(str(payload["cutoff_date"]))
        min_trust_score = float(payload["min_trust_score"])
    except (KeyError, TypeError, ValueError):
        return None
    return PostHogAIBetaRules(
        created_before=cutoff if cutoff.tzinfo is not None else cutoff.replace(tzinfo=UTC),
        min_trust_score=min_trust_score,
    )


def _resolve_beta(user: User, organization: "Organization") -> FeatureFlagResult | None:
    organization_id = str(organization.id)
    try:
        return posthoganalytics.get_feature_flag_result(
            POSTHOG_AI_BETA_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("posthog_ai_beta_flag_failed", exc_info=True)
        return None


def get_posthog_ai_access_decision(user: User, organization: "Organization") -> PostHogAIAccessDecision:
    """Fails closed: a denied or unresolved caller gets classic PostHog AI instead."""
    if not user or not user.is_authenticated or not user.distinct_id:
        return PostHogAIAccessDecision.UNRESOLVED

    if any(_resolve_flag(flag, user, organization) for flag in POSTHOG_AI_GRANDFATHERED_FLAGS):
        return PostHogAIAccessDecision.GRANDFATHERED

    beta = _resolve_beta(user, organization)
    if beta is None or not beta.enabled:
        return PostHogAIAccessDecision.BETA_OFF
    rules = _posthog_ai_beta_rules(beta.payload)
    if rules is None:
        logger.warning("posthog_ai_beta_rules_invalid", flag_key=POSTHOG_AI_BETA_FLAG)
        return PostHogAIAccessDecision.UNRESOLVED

    try:
        funding = _cached_funding_decision(user, organization, _POSTHOG_AI_FUNDING_CACHE_SECONDS)
    except DesktopAccessResolutionError:
        return PostHogAIAccessDecision.UNRESOLVED
    if funding == DesktopAccessDecision.STARTUP_PLAN:
        return PostHogAIAccessDecision.STARTUP_PROGRAM
    if funding == DesktopAccessDecision.PREPAID_CREDITS:
        return PostHogAIAccessDecision.PREPAID_CREDITS
    if organization.created_at >= rules.created_before:
        return PostHogAIAccessDecision.CREATED_AFTER_CUTOFF
    if best_customer_trust_score(organization) < rules.min_trust_score:
        return PostHogAIAccessDecision.LOW_TRUST
    return PostHogAIAccessDecision.ALLOWED


def has_loops_access(user: User, team: "Team | None" = None) -> bool:
    if not user.distinct_id:
        return False

    organization = team.organization if team is not None else getattr(user, "organization", None)
    organization_id = str(organization.id) if organization is not None else None
    return feature_enabled_or_false(
        "loops",
        str(user.distinct_id),
        groups={"organization": organization_id} if organization_id is not None else None,
        group_properties={"organization": {"id": organization_id}} if organization_id is not None else None,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
