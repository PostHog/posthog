from enum import StrEnum
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
import posthoganalytics

from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups as analytics_groups
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false, get_feature_flag_or_none

from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.metrics import DesktopAccessOutcome, observe_desktop_access_decision

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
DESKTOP_ACCESS_DECISION_EVENT = "desktop_access_decision"


class DesktopAccessResolutionError(Exception):
    pass


class DesktopAccessDecision(StrEnum):
    ALLOWED = "allowed"
    PREPAID_CREDITS = "prepaid_credits"

    @property
    def allowed(self) -> bool:
        return self == self.ALLOWED

    @property
    def reason(self) -> DesktopAccessReason | None:
        if self == self.PREPAID_CREDITS:
            return DesktopAccessReason.PREPAID_CREDITS
        return None


def _record_decision(
    outcome: DesktopAccessOutcome,
    *,
    user: User,
    organization: "Organization",
    startup_program_label: str | None = None,
) -> None:
    """The Prometheus counter says how often each outcome fires, but not to whom.

    The event carries the organization, so a refusal is attributable and support can
    name the organizations a gate change would unblock.
    """
    observe_desktop_access_decision(outcome=outcome)
    properties: dict[str, object] = {
        "outcome": outcome,
        "allowed": outcome in {"allowed", "override"},
        "organization_id": str(organization.id),
    }
    if startup_program_label is not None:
        properties["startup_program_label"] = startup_program_label
    try:
        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event=DESKTOP_ACCESS_DECISION_EVENT,
            properties=properties,
            groups=analytics_groups(organization=organization),
        )
    except Exception:
        logger.warning("desktop_access_decision_capture_failed", exc_info=True)


def _get_funding_status(user: User, organization: "Organization") -> OrganizationFundingStatus:
    try:
        return BillingManager(get_cached_instance_license(), user).get_funding_status(organization)
    except FundingStatusUnavailable as error:
        raise DesktopAccessResolutionError("Could not resolve organization funding status") from error


def get_desktop_access_decision(user: User, organization: "Organization") -> DesktopAccessDecision:
    if not user or not user.is_authenticated or not user.distinct_id:
        raise DesktopAccessResolutionError("Authentication is required to evaluate Desktop access")

    if settings.DEBUG:
        _record_decision("override", user=user, organization=organization)
        return DesktopAccessDecision.ALLOWED

    organization_id = str(organization.id)
    groups = {"organization": organization_id}
    group_properties = {"organization": {"id": organization_id}}
    override_enabled = get_feature_flag_or_none(
        DESKTOP_ACCESS_OVERRIDE_FLAG,
        str(user.distinct_id),
        groups=groups,
        group_properties=group_properties,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if not isinstance(override_enabled, bool):
        _record_decision("resolution_failure", user=user, organization=organization)
        raise DesktopAccessResolutionError("Could not evaluate the Desktop access override")
    if override_enabled:
        _record_decision("override", user=user, organization=organization)
        return DesktopAccessDecision.ALLOWED

    try:
        funding_status = _get_funding_status(user, organization)
    except DesktopAccessResolutionError:
        _record_decision("resolution_failure", user=user, organization=organization)
        raise

    # The decision does not read startup_program_label. The monthly posthog_code_usage billing
    # limit caps what a Startup or YC program organization can spend, so the program needs no block.
    startup_program_label = funding_status.startup_program_label
    if funding_status.prepaid_credit_state in {PrepaidCreditState.PENDING, PrepaidCreditState.ACTIVE}:
        _record_decision(
            "prepaid_credits", user=user, organization=organization, startup_program_label=startup_program_label
        )
        return DesktopAccessDecision.PREPAID_CREDITS

    _record_decision("allowed", user=user, organization=organization, startup_program_label=startup_program_label)
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
