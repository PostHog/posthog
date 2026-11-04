"""What every route that creates a logs alert shares: the per-team cap and the first check."""

import os
from datetime import UTC, datetime
from typing import Any

from posthog.models.team.team import Team

from products.alerts_platform.backend.facade.api import copied_legacy_ids, count_configurations, hold_admission_lock
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
    hold_admission_lock(team_id=team_id, source_kind=SourceKind.LOGS)
    check_alert_slot(team_id)


def check_alert_slot(team_id: int) -> None:
    """Raises `AlertLimitReached` when the team is at its cap. The caller holds the admission lock."""
    if team_id in UNCAPPED_ALERT_TEAM_IDS:
        return
    if _alerts_of(team_id) >= MAX_ALERTS_PER_TEAM:
        raise AlertLimitReached()


def _alerts_of(team_id: int) -> int:
    """Every logs alert of the team: each platform configuration, copies included, and each logs row
    with no copy. The count stays right once logs rows stop being written, and once they are deleted."""
    copied = copied_legacy_ids(team_id=team_id, source_kind=SourceKind.LOGS)
    uncopied = LogsAlertConfiguration.objects.filter(team_id=team_id).exclude(id__in=copied).count()
    return count_configurations(team_id=team_id, source_kind=SourceKind.LOGS) + uncopied


def first_check_at(team_id: int, schedule_restriction: dict[str, Any]) -> datetime:
    """When a new alert with quiet hours is first checked: now, or the end of the quiet window it is in."""
    return next_allowed_check_at(
        datetime.now(UTC),
        team_timezone=Team.objects.only("timezone").get(id=team_id).timezone,
        schedule_restriction=schedule_restriction,
    )
