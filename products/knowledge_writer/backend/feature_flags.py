import structlog
import posthoganalytics

from posthog.models.team import Team

logger = structlog.get_logger(__name__)

WRITER_FLAG = "knowledge-writer"
AGENT_LAUNCH_FLAG = "knowledge-writer-agent-launch"
OPEN_PULL_REQUESTS_FLAG = "knowledge-writer-open-prs"


def is_writer_enabled(team_id: int) -> bool:
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return False
    return is_team_flag_enabled(WRITER_FLAG, team)


def is_agent_launch_enabled(team: Team) -> bool:
    return is_team_flag_enabled(AGENT_LAUNCH_FLAG, team)


def open_pull_requests_flag_state(team: Team) -> bool | None:
    return team_flag_state(OPEN_PULL_REQUESTS_FLAG, team)


def is_team_flag_enabled(flag: str, team: Team) -> bool:
    return team_flag_state(flag, team) is True


def team_flag_state(flag: str, team: Team) -> bool | None:
    try:
        enabled = posthoganalytics.feature_enabled(
            flag,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("knowledge_writer_flag_check_failed", team_id=team.id, flag=flag)
        return None
    return enabled if isinstance(enabled, bool) else None
