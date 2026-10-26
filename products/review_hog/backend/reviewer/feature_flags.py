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


STANDARD_COORDINATOR_FLAG = "reviewhog-standard-coordinator"
PERFORMANCE_LENS_FOLLOW_UP_SPLIT_FLAG = "reviewhog-performance-lens-follow-up-split"


def _pull_request_flag_on(flag: str, repository: str, pr_number: int) -> bool:
    """Whether `flag` is on for this PR.

    Keyed by the PR, not the organization, so a percentage rollout splits the reviews of one organization
    and every turn of a PR gets the same answer. Any evaluation failure reads as off.
    """
    try:
        enabled = posthoganalytics.feature_enabled(flag, f"{repository}#{pr_number}", send_feature_flag_events=False)
    except Exception:
        logger.exception("Could not evaluate %s for %s#%s", flag, repository, pr_number)
        return False
    return enabled is True


def standard_coordinator_on(repository: str, pr_number: int) -> bool:
    """Whether this PR's Standard turns run their sessions as sub-agents of one coordinator session."""
    return _pull_request_flag_on(STANDARD_COORDINATOR_FLAG, repository, pr_number)


def skips_performance_lens_on_follow_ups(repository: str, pr_number: int) -> bool:
    """Whether this PR is in the treatment arm of the performance lens split.

    Its automatic follow-ups run without the performance lens. First reviews and turns a person asked for keep it.
    The flag's rollout percentage sets the size of the treatment arm.
    """
    return _pull_request_flag_on(PERFORMANCE_LENS_FOLLOW_UP_SPLIT_FLAG, repository, pr_number)
