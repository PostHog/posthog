from __future__ import annotations

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

RELEASES_AREA_FLAG = "releases-area"


def is_releases_enabled(team_id: int, *, distinct_id: str, email: str | None) -> bool:
    try:
        return feature_enabled_or_false(
            RELEASES_AREA_FLAG,
            distinct_id,
            groups={"project": str(team_id)},
            person_properties={"email": email},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
        )
    except Exception:
        logger.exception("releases_feature_flag_check_failed", team_id=team_id)
        return False
