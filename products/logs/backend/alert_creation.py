"""What every route that creates a logs alert shares: the per-team cap and the first check."""

import os
from datetime import UTC, datetime
from typing import Any

from posthog.models.team.team import Team

from products.alerts_platform.backend.facade.api import count_configurations, hold_cap_lock
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.alert_utils import next_allowed_check_at
from products.logs.backend.models import LogsAlertConfiguration

MAX_ALERTS_PER_TEAM = 20
# Comma-separated team IDs that bypass MAX_ALERTS_PER_TEAM. Configured via
# argocd for internal dogfood projects whose observability needs exceed the
# customer-facing cap; the cap's correctness assumptions (bounded N+1 in list,
# semaphore-sized fan-out in the Temporal activity) still hold for any team
# not in this set.
UNCAPPED_ALERT_TEAM_IDS: frozenset[int] = frozenset(
    int(t) for x in os.environ.get("LOGS_ALERTS_UNCAPPED_TEAM_IDS", "").split(",") if (t := x.strip()).isdigit()
)


class AlertLimitReached(Exception):
    def __init__(self) -> None:
        super().__init__(f"Maximum number of alerts ({MAX_ALERTS_PER_TEAM}) reached for this team.")


def claim_alert_slot(team_id: int) -> None:
    """Serializes the team's logs alert creates on every route, the platform's included, until the
    caller's transaction ends, and raises `AlertLimitReached` when the team is at its cap."""
    hold_cap_lock(team_id=team_id, source_kind=SourceKind.LOGS)
    check_alert_slot(team_id)


def check_alert_slot(team_id: int) -> None:
    """Raises `AlertLimitReached` when the team is at its cap. The caller holds the cap lock."""
    if team_id in UNCAPPED_ALERT_TEAM_IDS:
        return
    # Every logs row, and every platform alert with no logs row. A copy outlives its logs row when the
    # alert is deleted while logs owns it, so copies are not counted.
    alerts = LogsAlertConfiguration.objects.filter(team_id=team_id).count() + count_configurations(
        team_id=team_id, source_kind=SourceKind.LOGS, native_only=True
    )
    if alerts >= MAX_ALERTS_PER_TEAM:
        raise AlertLimitReached()


def first_check_at(team_id: int, schedule_restriction: dict[str, Any]) -> datetime:
    """When a new alert with quiet hours is first checked: now, or the end of the quiet window it is in."""
    return next_allowed_check_at(
        datetime.now(UTC),
        team_timezone=Team.objects.only("timezone").get(id=team_id).timezone,
        schedule_restriction=schedule_restriction,
    )
