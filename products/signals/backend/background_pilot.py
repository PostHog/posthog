"""Pilot telemetry for scouts that the background coordinator enrolls.

A background config (`managed_by=background`) runs for a project that did not set the scout
up, so each reaction to its output is pilot evidence. These events fire only for background
configs and their reports. The run events (`signals_scout_run_started` / `_finished`) carry
`managed_by` for run failure, and `$ai_generation` joins to them on `task_run_id` for cost.
"""

from __future__ import annotations

from typing import Any

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_authorship import resolve_background_authoring_runs

logger = structlog.get_logger(__name__)

BACKGROUND_REPORT_VIEWED_EVENT = "signals_background_report_viewed"
BACKGROUND_REPORT_RATED_EVENT = "signals_background_report_rated"
BACKGROUND_REPORT_DISMISSED_EVENT = "signals_background_report_dismissed"
BACKGROUND_SCOUT_OPTED_OUT_EVENT = "signals_background_scout_opted_out"

OPT_OUT_DISABLED = "disabled"
OPT_OUT_DELETED = "deleted"


def _capture(*, event: str, team: Team, user: User | None, properties: dict[str, Any]) -> None:
    try:
        posthoganalytics.capture(
            event=event,
            distinct_id=user.distinct_id if user is not None and user.distinct_id else str(team.uuid),
            properties={"team_id": team.id, **properties},
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning("signals_background_pilot: failed to capture event", event=event, team_id=team.id)


def capture_background_report_events(
    *, team: Team, user: User | None, event: str, report_ids: list[str], properties: dict[str, Any] | None = None
) -> None:
    """Capture `event` once for each report in `report_ids` that a background scout authored.

    Best-effort: a failed lookup or capture never fails the request that called it.
    """
    try:
        runs = resolve_background_authoring_runs(team.id, report_ids)
    except Exception:
        logger.warning("signals_background_pilot: failed to resolve report origin", event=event, team_id=team.id)
        return
    for report_id, run in runs.items():
        _capture(
            event=event,
            team=team,
            user=user,
            properties={
                "report_id": report_id,
                "scout_config_id": str(run.scout_config_id) if run.scout_config_id else None,
                "skill_name": run.skill_name,
                **(properties or {}),
            },
        )


def capture_background_scout_opted_out(*, config: SignalScoutConfig, user: User | None, action: str) -> None:
    """Capture that a person switched off or deleted a background config. Call it before the write."""
    if config.managed_by != SignalScoutConfig.ManagedBy.BACKGROUND:
        return
    _capture(
        event=BACKGROUND_SCOUT_OPTED_OUT_EVENT,
        team=config.team,
        user=user,
        properties={"scout_config_id": str(config.id), "skill_name": config.skill_name, "action": action},
    )
