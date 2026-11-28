"""Feature-flag gate for the user journeys product.

User journeys is unreleased, so nothing here runs for a team until ``user-journeys`` is switched
on for that team. The frontend reads the same flag to show the scene.

The gate evaluates against the ``project`` group keyed on team ID alone, so it needs no ``Team``
row and no database read.
"""

from __future__ import annotations

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

USER_JOURNEYS_FLAG = "user-journeys"


def is_user_journeys_enabled(team_id: int) -> bool:
    try:
        return feature_enabled_or_false(
            USER_JOURNEYS_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            # Later phases check journeys per team on a schedule, so leaving this on would emit a
            # $feature_flag_called event for every team on every run.
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased product stays off when the flags service is unreachable, rather than
        # defaulting on or failing the caller.
        logger.exception("user_journeys_feature_flag_check_failed", team_id=team_id)
        return False
