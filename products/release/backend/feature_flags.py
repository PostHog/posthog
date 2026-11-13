from __future__ import annotations

from uuid import UUID

import structlog
import posthoganalytics

logger = structlog.get_logger(__name__)

RELEASES_AREA_FLAG = "releases-area"


class ReleasesGateUnavailable(Exception):
    pass


def is_releases_enabled(
    *,
    team_id: int,
    team_uuid: UUID,
    organization_id: UUID,
    distinct_id: str,
    email: str | None,
    raise_on_error: bool = False,
) -> bool:
    try:
        enabled = posthoganalytics.feature_enabled(
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
        if raise_on_error:
            raise
        return False
    if enabled is None and raise_on_error and not posthoganalytics.disabled:
        raise ReleasesGateUnavailable(team_id)
    return enabled is True
