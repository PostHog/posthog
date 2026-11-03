import logging

import posthoganalytics

from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.constants import CONTROL_ARM_SET, SINGLE_AGENT_ARM_SETS

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
ZERO_CHANGE_SKIP_FLAG = "reviewhog-zero-change-skip"
DELTA_BAND_FLAG = "reviewhog-delta-band"
# Its variant names an entry of SINGLE_AGENT_ARM_SETS. Turned off, it moves every new turn to the control set.
SINGLE_AGENT_ARMS_FLAG = "reviewhog-single-agent-arms"


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


def skips_zero_change_follow_ups(repository: str, pr_number: int) -> bool:
    """Whether this PR is in the treatment arm of the zero-change split: the gate skips a push whose PR diff did not change."""
    return _pull_request_flag_on(ZERO_CHANGE_SKIP_FLAG, repository, pr_number)


def delta_reviews_low_risk_follow_ups(repository: str, pr_number: int) -> bool:
    """Whether this PR is in the treatment arm of the delta split: low-risk later follow-ups review only what changed."""
    return _pull_request_flag_on(DELTA_BAND_FLAG, repository, pr_number)


def single_agent_arm_set(repository: str, pr_number: int) -> str:
    """The arm set this PR's Standard sessions run on, keyed by the PR like the flags above.

    No variant, a variant with no arm set, or an evaluation failure runs the control set.
    """
    try:
        variant = posthoganalytics.get_feature_flag(
            SINGLE_AGENT_ARMS_FLAG, f"{repository}#{pr_number}", send_feature_flag_events=False
        )
    except Exception:
        logger.exception("Could not evaluate %s for %s#%s", SINGLE_AGENT_ARMS_FLAG, repository, pr_number)
        return CONTROL_ARM_SET
    return variant if isinstance(variant, str) and variant in SINGLE_AGENT_ARM_SETS else CONTROL_ARM_SET
