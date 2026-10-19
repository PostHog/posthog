"""Who may see the ranking model's output in the inbox: the model sorts and the strength of each report's score.

Staff always may. Other users need the `inbox-model-sort` flag, keyed by user with the project and organization
groups the web client registers, so the API agrees with the inbox menu. A flag that fails to evaluate denies access.
Raw probabilities and model metadata stay staff only.
"""

import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

INBOX_MODEL_SORT_FLAG = "inbox-model-sort"


def can_view_inbox_ranking(user: User, team: Team) -> bool:
    if user.is_staff:
        return True
    if not user.distinct_id:
        return False
    try:
        return feature_enabled_or_false(
            INBOX_MODEL_SORT_FLAG,
            user.distinct_id,
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": team.id, "uuid": str(team.uuid)},
            },
        )
    except Exception:
        logger.exception("signals.inbox_ranking.flag_failed", team_id=team.id, user_id=user.id)
        return False
