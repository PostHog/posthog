import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.workflows.backend.facade.contracts import SendingLimits
from products.workflows.backend.services.email_health import team_email_sending_allowance
from products.workflows.backend.utils.email_sending_tiers import is_tier_enforced

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

logger = structlog.get_logger(__name__)


@frozen
class DailyEmailCap:
    emails_per_day: int
    reached: bool


def get_team_sending_limits(team: Team, *, include_daily_email_cap: bool) -> SendingLimits:
    """
    A notice must never take the scene down with it, so every lookup fails open to "not limited".
    The daily cap is project-wide usage, so callers include it only for people who can read every workflow.
    """
    quota_limited = _quota_limited_resources(team)
    daily_cap = _daily_email_cap(team.id) if include_daily_email_cap else None
    return SendingLimits(
        email_quota_limited=quota_limited[QuotaResource.WORKFLOW_EMAILS],
        destination_quota_limited=quota_limited[QuotaResource.WORKFLOW_DESTINATIONS],
        email_daily_cap_reached=daily_cap is not None and daily_cap.reached,
        emails_per_day=daily_cap.emails_per_day if daily_cap else None,
    )


def _quota_limited_resources(team: Team) -> dict[QuotaResource, bool]:
    try:
        return get_fresh_team_limited_resources(team.api_token)
    except Exception:
        logger.warning("workflows_sending_limits_quota_check_failed", team_id=team.id, exc_info=True)
        return dict.fromkeys(QuotaResource, False)


def _daily_email_cap(team_id: int) -> DailyEmailCap | None:
    if not is_tier_enforced():
        return None
    try:
        allowance = team_email_sending_allowance(team_id)
    except Exception:
        logger.warning("workflows_sending_limits_allowance_check_failed", team_id=team_id, exc_info=True)
        return None
    if not allowance.enforced:
        return None
    return DailyEmailCap(emails_per_day=allowance.emails_per_day, reached=allowance.daily_cap_reached)
