from __future__ import annotations

from uuid import UUID

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

RELEASES_AREA_FLAG = "releases-area"


def is_releases_enabled(
    *, team_id: int, team_uuid: UUID, organization_id: UUID, distinct_id: str, email: str | None
) -> bool:
    try:
        return feature_enabled_or_false(
            RELEASES_AREA_FLAG,
            distinct_id,
            groups={"organization": str(organization_id), "project": str(team_uuid)},
            person_properties={"email": email},
            group_properties={"organization": {"id": str(organization_id)}, "project": {"id": team_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("releases_feature_flag_check_failed", team_id=team_id)
        return False
