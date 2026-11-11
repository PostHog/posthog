import structlog

from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_value

logger = structlog.get_logger(__name__)

UI_CUSTOMIZATION_FLAG = "ui-customization"


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether UI customization is enabled for this person. Fails closed."""
    try:
        return (
            posthog_feature_flag_value(
                UI_CUSTOMIZATION_FLAG,
                str(user.distinct_id),
                organization_id=team.organization_id,
                team_id=team.id,
                person_properties={"email": user.email},
            )
            is True
        )
    except Exception:
        logger.warning("ui_customization_flag_check_failed", exc_info=True)
        return False
