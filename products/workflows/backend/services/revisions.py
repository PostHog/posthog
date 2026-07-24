import structlog
import posthoganalytics

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

WORKFLOWS_REVISIONS_FLAG = "workflows-revisions"


def use_workflows_revisions(team: Team) -> bool:
    """Gates the draft → test → publish cycle on active workflows; off means today's behavior
    (active workflows are read-only via MCP).

    A raised exception (Redis/HyperCache blip, network glitch, SDK bug) is treated as "flag off" —
    the rejection path is the safe fallback, making the flag a kill switch for the whole cycle.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WORKFLOWS_REVISIONS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
            )
        )
    except Exception:
        logger.warning(
            "workflows.revisions.feature_flag_check_failed_defaulting_off",
            team_id=team.id,
            flag=WORKFLOWS_REVISIONS_FLAG,
            exc_info=True,
        )
        return False
