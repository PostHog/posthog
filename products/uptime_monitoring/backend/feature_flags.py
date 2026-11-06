"""Feature-flag gate for the uptime monitoring product.

Uptime monitoring is unreleased, so nothing here runs for a team until
``uptime-monitoring`` is switched on for that team. The frontend reads the
same flag to show the scene.

The gate evaluates against the ``project`` group keyed on team ID alone, so it
needs no ``Team`` row and no database read.
"""

from __future__ import annotations

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

UPTIME_MONITORING_FLAG = "uptime-monitoring"


def is_uptime_monitoring_enabled(team_id: int) -> bool:
    try:
        return feature_enabled_or_false(
            UPTIME_MONITORING_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            # Checks run per team on a schedule, so leaving this on would emit a
            # $feature_flag_called event for every team on every tick.
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased product stays off when the flags service is unreachable,
        # rather than defaulting on or failing the caller's run.
        logger.exception("uptime_monitoring_feature_flag_check_failed", team_id=team_id)
        return False
