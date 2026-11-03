"""Who gets the Today home and its decision model."""

from django.core.cache import cache

import structlog
import posthoganalytics

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

TODAY_RAIL_NAV_FLAG = "today-rail-nav"
TODAY_REPORT_JEV_FLAG = "today-report-jev"
TODAY_PROGRESSIVE_PULSE_FLAG = "today-progressive-pulse"
TODAY_FLAGS = (TODAY_RAIL_NAV_FLAG, TODAY_REPORT_JEV_FLAG, TODAY_PROGRESSIVE_PULSE_FLAG)
API_FLAGS_CACHE_SECONDS = 60


def progressive_pulse_enabled(user: User, team: Team) -> bool:
    return _flag_on(TODAY_PROGRESSIVE_PULSE_FLAG, user, team)


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether the new navigation (and so the Today home) is on for this person. Fails closed."""
    return _flag_on(TODAY_RAIL_NAV_FLAG, user, team)


def _groups(team: Team) -> dict[str, str]:
    return {"organization": str(team.organization_id), "project": str(team.id)}


def _group_properties(team: Team) -> dict[str, dict[str, str]]:
    return {"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}}


def _flag_on(flag: str, user: User, team: Team) -> bool:
    if _local_flag_on(TODAY_RAIL_NAV_FLAG, user, team):
        return flag == TODAY_RAIL_NAV_FLAG or _local_flag_on(flag, user, team)
    return _api_flags(user, team).get(flag, False)


def _api_flags(user: User, team: Team) -> dict[str, bool]:
    key = f"today_flags:{team.id}:{user.id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        decision = posthoganalytics.setup().get_flags_decision(
            str(user.distinct_id),
            groups=_groups(team),
            person_properties={"email": user.email},
            group_properties=_group_properties(team),
            flag_keys_to_evaluate=list(TODAY_FLAGS),
        )
    except Exception:
        logger.warning("today_flag_check_failed", exc_info=True)
        return {}
    found = decision.get("flags") or {}
    if decision.get("errorsWhileComputingFlags") or TODAY_RAIL_NAV_FLAG not in found:
        return {}
    flags = {name: found[name].enabled is True for name in TODAY_FLAGS if name in found}
    cache.set(key, flags, API_FLAGS_CACHE_SECONDS)
    return flags


def _local_flag_on(flag: str, user: User, team: Team) -> bool:
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
