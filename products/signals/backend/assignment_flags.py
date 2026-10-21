import structlog

from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)


def _enabled(key: str, team_id: int) -> bool:
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
        return (
            feature_enabled_or_false(
                key,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.exception("signals.assignment.flag_check_failed", team_id=team_id, flag=key)
        return False


def assignment_agent_selection_enabled(team_id: int) -> bool:
    return _enabled("signals-assignment-agent-selection", team_id)


def assignment_github_application_enabled(team_id: int) -> bool:
    return _enabled("signals-assignment-github-application", team_id)
