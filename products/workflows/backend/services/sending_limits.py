import structlog

from posthog.models.team import Team

from products.workflows.backend.facade.contracts import SendingLimits

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

logger = structlog.get_logger(__name__)


def get_team_sending_limits(team: Team) -> SendingLimits:
    """A notice must never take the scene down with it, so a failed lookup reads as "not limited"."""
    quota_limited = _quota_limited_resources(team)
    return SendingLimits(
        email_quota_limited=quota_limited[QuotaResource.WORKFLOW_EMAILS],
        destination_quota_limited=quota_limited[QuotaResource.WORKFLOW_DESTINATIONS],
    )


def _quota_limited_resources(team: Team) -> dict[QuotaResource, bool]:
    try:
        return get_fresh_team_limited_resources(team.api_token)
    except Exception:
        logger.warning("workflows_sending_limits_quota_check_failed", team_id=team.id, exc_info=True)
        return dict.fromkeys(QuotaResource, False)
