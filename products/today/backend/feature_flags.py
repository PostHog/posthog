"""Who gets a Today briefing.

The briefing is part of the new navigation, so it uses the same flag: a person gets a briefing
only when `today-rail-nav` is on for them. The API checks the flag; the scheduler and the agent
run, which act without a request, also check that the person can still open the project.
"""

import structlog

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

TODAY_RAIL_NAV_FLAG = "today-rail-nav"


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether the new navigation (and so the briefing) is on for this person. Fails closed."""
    try:
        return feature_enabled_or_false(
            TODAY_RAIL_NAV_FLAG,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            person_properties={"email": user.email},
            only_evaluate_locally=False,
            # The scheduler checks every recent viewer on every tick, so no $feature_flag_called event per call.
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("today_flag_check_failed", exc_info=True)
        return False


def may_get_briefing(user: User, team: Team) -> bool:
    """Whether a run may start for this person outside a request. Someone who opened Today may have
    left the organization or lost the project since, and must not get its data gathered for them."""
    return user.teams.filter(id=team.id).exists() and is_enabled_for(user, team)
