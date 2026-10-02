"""Who gets a Today briefing. Everyone else sees the report list."""

import structlog

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)

# The briefing is part of the new navigation, so it uses the same flag.
TODAY_RAIL_NAV_FLAG = "today-rail-nav"


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether the new navigation (and so the briefing) is on for this person. Fails closed."""
    try:
        return feature_enabled_or_false(
            TODAY_RAIL_NAV_FLAG,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}},
            person_properties={"email": user.email},
            only_evaluate_locally=False,
            # The scheduler checks every recent viewer on every tick, so no $feature_flag_called event per call.
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("today_flag_check_failed", exc_info=True)
        return False


def may_get_briefing(user: User, team: Team) -> bool:
    """Whether a briefing may be written for this person right now.

    The organization must have approved AI data processing and have AI credits left, the person
    must still be able to open the project, and the flag must be on for them. The API, the
    scheduler and the run all ask this, so a person who fails it gets the report list and
    no row, no workflow and no LLM call.
    """
    return bool(
        team.organization.is_ai_data_processing_approved
        and not is_team_limited(team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
        and user.teams.filter(id=team.id).exists()
        and is_enabled_for(user, team)
    )
