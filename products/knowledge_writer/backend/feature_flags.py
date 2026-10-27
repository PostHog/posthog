import structlog
import posthoganalytics

from posthog.models.team import Team

logger = structlog.get_logger(__name__)

AGENT_LAUNCH_FLAG = "knowledge-writer-agent-launch"


def is_agent_launch_enabled(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AGENT_LAUNCH_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("knowledge_writer_flag_check_failed", team_id=team.id)
        return False
