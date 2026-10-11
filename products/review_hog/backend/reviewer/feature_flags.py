import logging

import posthoganalytics

from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

FLASH_PIPELINE_KILL_SWITCH_FLAG = "reviewhog-flash-pipeline-kill-switch"


def flash_pipeline_kill_switch_on(team_id: int) -> bool:
    """Whether the kill switch moves this team's Flash turns back to the pipeline, keyed by organization.

    Any evaluation failure reads as off, so a flag service outage keeps Flash on its code default.
    """
    try:
        organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return False
        enabled = posthoganalytics.feature_enabled(
            FLASH_PIPELINE_KILL_SWITCH_FLAG,
            str(organization_id),
            groups={"organization": str(organization_id)},
            group_properties={"organization": {"id": str(organization_id)}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception(
            "Could not evaluate %s for team %s; using the default Flash design",
            FLASH_PIPELINE_KILL_SWITCH_FLAG,
            team_id,
        )
        return False
    return enabled is True
