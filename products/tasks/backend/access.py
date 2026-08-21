from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.models.user import User

from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.metrics import observe_desktop_access_decision

from ee.billing.billing_manager import (
    BillingManager,
    FundingStatusUnavailable,
    OrganizationFundingStatus,
    PrepaidCreditState,
)

if TYPE_CHECKING:
    from posthog.models.team.team import Team

DESKTOP_ACCESS_GATE_FLAG = "posthog-desktop-access-gate"
DESKTOP_ACCESS_OVERRIDE_FLAG = "posthog-desktop-access-override"


class DesktopAccessResolutionError(Exception):
    pass


@frozen
class DesktopAccessDecision:
    reason: DesktopAccessReason | None = None

    @property
    def allowed(self) -> bool:
        return self.reason is None


def _is_flag_enabled(
    flag_key: str,
    user: User,
    team: "Team | None" = None,
    *,
    require_boolean: bool = False,
) -> bool | None:
    if not user.distinct_id:
        return None
    org = team.organization if team is not None else getattr(user, "organization", None)
    kwargs: dict[str, Any] = {
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }
    if org is not None:
        org_id = str(org.id)
        kwargs["groups"] = {"organization": org_id}
        kwargs["group_properties"] = {"organization": {"id": org_id}}
    if require_boolean:
        result = posthoganalytics.get_feature_flag(flag_key, user.distinct_id, **kwargs)
        return result if isinstance(result, bool) else None

    result = posthoganalytics.feature_enabled(flag_key, user.distinct_id, **kwargs)
    return bool(result) if result is not None else None


def _is_rollout_enabled(user: User, team: "Team") -> bool | None:
    return _is_flag_enabled(DESKTOP_ACCESS_GATE_FLAG, user, team)


def _get_funding_status(user: User, team: "Team") -> OrganizationFundingStatus:
    try:
        return BillingManager(get_cached_instance_license(), user).get_funding_status(team.organization)
    except FundingStatusUnavailable as error:
        raise DesktopAccessResolutionError("Could not resolve organization funding status") from error


def get_desktop_access_decision(user: User, team: "Team") -> DesktopAccessDecision:
    if not user or not user.is_authenticated:
        raise DesktopAccessResolutionError("Authentication is required to evaluate Desktop access")

    try:
        rollout_enabled = _is_rollout_enabled(user, team)
    except Exception as error:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access rollout") from error

    if rollout_enabled is None:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access rollout")
    if not rollout_enabled:
        return DesktopAccessDecision()

    try:
        override_enabled = _is_flag_enabled(DESKTOP_ACCESS_OVERRIDE_FLAG, user, team, require_boolean=True)
    except Exception as error:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access override") from error

    if not isinstance(override_enabled, bool):
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access override")
    if override_enabled:
        observe_desktop_access_decision(outcome="override")
        return DesktopAccessDecision()

    try:
        funding_status = _get_funding_status(user, team)
    except DesktopAccessResolutionError:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise

    if funding_status.startup_program_label is not None:
        observe_desktop_access_decision(outcome="startup_plan")
        return DesktopAccessDecision(reason=DesktopAccessReason.STARTUP_PLAN)
    if funding_status.prepaid_credit_state in {PrepaidCreditState.PENDING, PrepaidCreditState.ACTIVE}:
        observe_desktop_access_decision(outcome="prepaid_credits")
        return DesktopAccessDecision(reason=DesktopAccessReason.PREPAID_CREDITS)

    observe_desktop_access_decision(outcome="allowed")
    return DesktopAccessDecision()


def has_loops_access(user: User, team: "Team | None" = None) -> bool:
    return bool(_is_flag_enabled("loops", user, team))
