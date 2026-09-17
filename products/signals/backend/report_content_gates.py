"""Organization-level rollout gates for report metrics.

The checks live in their own module because they need `Team` and the flag client.
Report models and Temporal payloads import `report_metrics.py` during process setup,
so that module must not import these dependencies.

A metric gate binds every writer, not only the authoring agent: a stored metric definition is also a
query that the refresh path runs later.
"""

from uuid import UUID

from django.conf import settings

import structlog

from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

REPORT_METRICS_FLAG = "signals-report-metrics"


def _organization_flag_enabled(flag: str, organization_id: UUID) -> bool:
    """Read one organization-keyed rollout flag.

    The flag is evaluated for every call so a flip takes effect immediately, and is on in DEBUG for
    local coverage. It fails closed, because a flag-service error must not add content to the reports
    of an organization that is not opted in.
    """
    if settings.DEBUG:
        return True
    try:
        return feature_enabled_or_false(
            flag,
            str(organization_id),
            groups={"organization": str(organization_id)},
            group_properties={"organization": {"id": str(organization_id)}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning(
            "signals report content flag check failed", flag=flag, organization_id=organization_id, exc_info=True
        )
        return False


def _team_flag_enabled(flag: str, team_id: int) -> bool:
    """The `team_id` adapter for callers that hold an id instead of a `Team`, such as a Temporal
    activity input. Fails closed, so a team that cannot be read gets no report content."""
    if settings.DEBUG:
        return True
    try:
        organization_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    except Exception:
        logger.warning(
            "signals report content flag check could not resolve the team", flag=flag, team_id=team_id, exc_info=True
        )
        return False
    return _organization_flag_enabled(flag, organization_id)


def organization_report_metrics_enabled(organization_id: UUID) -> bool:
    return _organization_flag_enabled(REPORT_METRICS_FLAG, organization_id)


def team_report_metrics_enabled(team_id: int) -> bool:
    return _team_flag_enabled(REPORT_METRICS_FLAG, team_id)
