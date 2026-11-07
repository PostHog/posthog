import structlog

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

UI_CUSTOMIZATION_FLAG = "ui-customization"


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether UI customization is enabled for this person. Fails closed."""
    return _flag_on(UI_CUSTOMIZATION_FLAG, user, team)


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
            # The API checks the flag on every call, so no $feature_flag_called event per call.
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("ui_customization_flag_check_failed", exc_info=True)
        return False
