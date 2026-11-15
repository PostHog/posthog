"""Who gets the Today home and its decision model."""

import structlog

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

TODAY_RAIL_NAV_FLAG = "today-rail-nav"
TODAY_REPORT_JEV_FLAG = "today-report-jev"


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether the new navigation (and so the Today home) is on for this person. Fails closed."""
    return _flag_on(TODAY_RAIL_NAV_FLAG, user, team)


def _groups(team: Team) -> dict[str, str]:
    return {"organization": str(team.organization_id), "project": str(team.id)}


def _group_properties(team: Team) -> dict[str, dict[str, str]]:
    return {"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}}


def _flag_on(flag: str, user: User, team: Team) -> bool:
    try:
        return feature_enabled_or_false(
            flag,
            str(user.distinct_id),
            groups=_groups(team),
            group_properties=_group_properties(team),
            person_properties={"email": user.email},
            only_evaluate_locally=False,
            # The home checks the flag on every call, so no $feature_flag_called event per call.
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("today_flag_check_failed", exc_info=True)
        return False


def may_ask_jev(user: User, team: Team) -> bool:
    """Jev calls are not billed as AI credits, so they skip the organization's credit limit."""
    return _may_send_to_ai(user, team) and all(
        _flag_on(flag, user, team) for flag in (TODAY_REPORT_JEV_FLAG, TODAY_RAIL_NAV_FLAG)
    )


def _may_send_to_ai(user: User, team: Team) -> bool:
    return bool(team.organization.is_ai_data_processing_approved and user.teams.filter(id=team.id).exists())
