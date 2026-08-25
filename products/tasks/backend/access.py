from enum import StrEnum
from typing import TYPE_CHECKING

from posthog.cloud_utils import get_cached_instance_license
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false, get_feature_flag_or_none

from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.metrics import observe_desktop_access_decision
from products.tasks.backend.models import CodeInviteRedemption

from ee.billing.billing_manager import (
    BillingManager,
    FundingStatusUnavailable,
    OrganizationFundingStatus,
    PrepaidCreditState,
)

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team

DESKTOP_ACCESS_GATE_FLAG = "posthog-desktop-access-gate"
DESKTOP_ACCESS_OVERRIDE_FLAG = "posthog-desktop-access-override"


class DesktopAccessResolutionError(Exception):
    pass


class DesktopAccessDecision(StrEnum):
    ALLOWED = "allowed"
    LEGACY_ACCESS_REQUIRED = "legacy_access_required"
    STARTUP_PLAN = "startup_plan"
    PREPAID_CREDITS = "prepaid_credits"

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


# Either flag grants the same access. `tasks` is the Desktop waitlist. `phai-sandbox-mode` is the
# PostHog AI composer, which reaches the same cloud runs through a different entry point, and rolls
# out to organizations that are not on the Desktop waitlist.
TASKS_ACCESS_FEATURE_FLAGS = ("tasks", "phai-sandbox-mode")


def has_tasks_access(user: User) -> bool:
    """
    User has access to PostHog Desktop if one of the `TASKS_ACCESS_FEATURE_FLAGS` is enabled for
    them OR they have redeemed an invite code.
    """
    if not user or not user.is_authenticated or not user.distinct_id:
        return False

    organization = getattr(user, "organization", None)
    organization_id = str(organization.id) if organization is not None else None
    if any(
        feature_enabled_or_false(
            flag_key,
            str(user.distinct_id),
            groups={"organization": organization_id} if organization_id is not None else None,
            group_properties={"organization": {"id": organization_id}} if organization_id is not None else None,
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        for flag_key in TASKS_ACCESS_FEATURE_FLAGS
    ):
        return True
    return CodeInviteRedemption.objects.filter(user=user).exists()


def _get_funding_status(user: User, organization: "Organization") -> OrganizationFundingStatus:
    try:
        return BillingManager(get_cached_instance_license(), user).get_funding_status(organization)
    except FundingStatusUnavailable as error:
        raise DesktopAccessResolutionError("Could not resolve organization funding status") from error


def get_desktop_access_decision(user: User, organization: "Organization") -> DesktopAccessDecision:
    if not user or not user.is_authenticated or not user.distinct_id:
        raise DesktopAccessResolutionError("Authentication is required to evaluate Desktop access")

    organization_id = str(organization.id)
    groups = {"organization": organization_id}
    group_properties = {"organization": {"id": organization_id}}
    rollout_enabled = get_feature_flag_or_none(
        DESKTOP_ACCESS_GATE_FLAG,
        str(user.distinct_id),
        groups=groups,
        group_properties=group_properties,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if not isinstance(rollout_enabled, bool):
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access rollout")
    if not rollout_enabled:
        try:
            legacy_access_allowed = has_tasks_access(user)
        except Exception as error:
            observe_desktop_access_decision(outcome="resolution_failure")
            raise DesktopAccessResolutionError("Could not evaluate legacy Desktop access") from error
        if legacy_access_allowed:
            observe_desktop_access_decision(outcome="legacy_allowed")
            return DesktopAccessDecision.ALLOWED
        observe_desktop_access_decision(outcome="legacy_denied")
        return DesktopAccessDecision.LEGACY_ACCESS_REQUIRED

    override_enabled = get_feature_flag_or_none(
        DESKTOP_ACCESS_OVERRIDE_FLAG,
        str(user.distinct_id),
        groups=groups,
        group_properties=group_properties,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if not isinstance(override_enabled, bool):
        observe_desktop_access_decision(outcome="resolution_failure")
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access override")
    if override_enabled:
        observe_desktop_access_decision(outcome="override")
        return DesktopAccessDecision.ALLOWED

    try:
        funding_status = _get_funding_status(user, organization)
    except DesktopAccessResolutionError:
        observe_desktop_access_decision(outcome="resolution_failure")
        raise

    if funding_status.startup_program_label is not None:
        observe_desktop_access_decision(outcome="startup_plan")
        return DesktopAccessDecision.STARTUP_PLAN
    if funding_status.prepaid_credit_state in {PrepaidCreditState.PENDING, PrepaidCreditState.ACTIVE}:
        observe_desktop_access_decision(outcome="prepaid_credits")
        return DesktopAccessDecision.PREPAID_CREDITS

    observe_desktop_access_decision(outcome="allowed")
    return DesktopAccessDecision.ALLOWED


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
