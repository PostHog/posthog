from typing import TYPE_CHECKING

import structlog
import posthoganalytics

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

LOGS_ARCHIVE_FEATURE_FLAG = "logs-archive-search"


def archive_enabled(user: "User | AnonymousUser | None", team: "Team") -> bool:
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                LOGS_ARCHIVE_FEATURE_FLAG,
                str(distinct_id),
                groups={"organization": organization_id, "project": project_id},
                group_properties={
                    "organization": {"id": organization_id},
                    "project": {"id": project_id},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("logs_archive_flag_check_failed", team_id=team.id)
        return False


def use_archive_requested(user: "User | AnonymousUser | None", team: "Team", requested: bool) -> bool:
    """Route to the archive only when the client explicitly asks for it and the flag is on.

    The Archive tab in the logs viewer sends `useArchive: true`; the regular viewer never does.
    The feature flag remains the hard gate, so a stray `useArchive` from a non-flagged client is
    ignored and falls back to the hot table.
    """
    return bool(requested) and archive_enabled(user, team)
