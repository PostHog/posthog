"""Who may see the ranking model's output in the inbox: the model sorts and the strength of each report's score.

Staff always may. Other users need the `inbox-model-sort` flag. It is evaluated locally, with the person and group
properties the web client registers (`frontend/src/lib/utils/posthogIdentity.ts`), so the API agrees with the inbox
menu without a remote flag call on every inbox request. A flag that fails to evaluate denies access.
Users with access see the served model key, probabilities and lifts. The manifest version and the model metadata
stay in the `ranking_score` artefacts.
"""

import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.utils import get_instance_realm

logger = structlog.get_logger(__name__)

INBOX_MODEL_SORT_FLAG = "inbox-model-sort"


def can_view_inbox_ranking(user: User, team: Team) -> bool:
    if user.is_staff:
        return True
    if not user.distinct_id:
        return False
    organization = team.organization
    try:
        return feature_enabled_or_false(
            INBOX_MODEL_SORT_FLAG,
            user.distinct_id,
            groups={"organization": str(organization.id), "project": str(team.uuid)},
            person_properties={
                "email": None if user.anonymize_data else user.email,
                "realm": get_instance_realm(),
            },
            group_properties={
                "organization": {
                    "id": str(organization.id),
                    "name": organization.name,
                    "slug": organization.slug,
                    "created_at": organization.created_at.isoformat(),
                },
                "project": {
                    "id": team.id,
                    "uuid": str(team.uuid),
                    "name": team.name,
                    "ingested_event": team.ingested_event,
                    "is_demo": team.is_demo,
                    "timezone": team.timezone,
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("signals.inbox_ranking.flag_failed", team_id=team.id, user_id=user.id)
        return False
