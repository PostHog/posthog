import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.workflows.backend.services.email_sending_allowance import team_email_sending_allowance

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

logger = structlog.get_logger(__name__)


@frozen
class SendingLimits:
    """Which project-wide limits currently stop or delay workflow sends."""

    email_quota_limited: bool
    destination_quota_limited: bool
    email_daily_cap_reached: bool
    emails_per_day: int | None


def get_team_sending_limits(team: Team) -> SendingLimits:
    quota_limited = _quota_limited_resources(team)
    allowance = team_email_sending_allowance(team.id)
    return SendingLimits(
        email_quota_limited=quota_limited[QuotaResource.WORKFLOW_EMAILS],
        destination_quota_limited=quota_limited[QuotaResource.WORKFLOW_DESTINATIONS],
        email_daily_cap_reached=allowance.daily_cap_reached,
        emails_per_day=allowance.emails_per_day if allowance.enforced else None,
    )


def _quota_limited_resources(team: Team) -> dict[QuotaResource, bool]:
    # A notice must never take the scene down with it, so a quota limiter blip reads as "not limited".
    try:
        return get_fresh_team_limited_resources(team.api_token)
    except Exception:
        logger.warning("workflows_sending_limits_quota_check_failed", team_id=team.id, exc_info=True)
        return dict.fromkeys(QuotaResource, False)
