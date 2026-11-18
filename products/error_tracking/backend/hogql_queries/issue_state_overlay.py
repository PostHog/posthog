import datetime
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssue

RECENT_ISSUE_STATE_WINDOW = datetime.timedelta(seconds=60)

# The bulk endpoint has no issue count limit, so skip the overlay instead of sending an unbounded
# external table when many issues change within one window.
MAX_RECENT_ISSUE_STATES = 100

RECENT_ISSUE_STATE_ROW_COUNT = Histogram(
    "error_tracking_recent_issue_state_row_count",
    "Number of recent Postgres issue-state rows loaded before applying the external-table limit",
    buckets=(0, 1, 5, 10, 25, 50, 100, 101, float("inf")),
)

# These reads pin to the primary (read-after-write freshness), so they cannot fall back to a replica.
# When the primary times out, the query degrades without the overlay; count each degraded read here.
RECENT_ISSUE_STATE_OVERLAY_UNAVAILABLE = Counter(
    "error_tracking_recent_issue_state_overlay_unavailable_total",
    "Times an error tracking overlay Postgres read failed and the query ran without the overlay",
    ["read"],
)


@frozen
class RecentIssueState:
    team_id: int
    issue_id: UUID
    issue_status: str
    issue_severity: str | None
    issue_name: str | None
    issue_description: str | None
    assigned_user_id: int | None
    assigned_role_id: UUID | None

    def as_external_table_row(self) -> dict[str, object]:
        return {
            "team_id": self.team_id,
            "issue_id": self.issue_id,
            "issue_status": self.issue_status,
            "issue_severity": self.issue_severity,
            "issue_name": self.issue_name,
            "issue_description": self.issue_description,
            "assigned_user_id": self.assigned_user_id,
            "assigned_role_id": self.assigned_role_id,
            "is_present": True,
        }


def latest_issue_state_watermark(team_id: int) -> datetime.datetime | None:
    return (
        ErrorTrackingIssue.objects.using(DEFAULT_DB_ALIAS)
        .filter(team_id=team_id, state_updated_at__isnull=False)
        .order_by("-state_updated_at")
        .values_list("state_updated_at", flat=True)
        .first()
    )


def issue_state_changed_within_window(
    watermark: datetime.datetime | None, *, current_time: datetime.datetime | None = None
) -> bool:
    """Whether load_recent_issue_states can return a row, given the team's latest state change.

    The watermark is the newest state_updated_at on the team, so a watermark outside the window
    means no row can pass the overlay filter and the read is guaranteed to return nothing.
    """
    if watermark is None:
        return False
    return watermark >= (current_time or timezone.now()) - RECENT_ISSUE_STATE_WINDOW


def load_recent_issue_states(team_id: int, *, current_time: datetime.datetime | None = None) -> list[RecentIssueState]:
    threshold = (current_time or timezone.now()) - RECENT_ISSUE_STATE_WINDOW
    # The filter matches the partial (team, state_updated_at) index, which this read depends on.
    rows = list(
        ErrorTrackingIssue.objects.using(DEFAULT_DB_ALIAS)
        .filter(team_id=team_id, state_updated_at__gte=threshold)
        .values(
            "id",
            "status",
            "severity",
            "name",
            "description",
            "assignment__user_id",
            "assignment__role_id",
        )[: MAX_RECENT_ISSUE_STATES + 1]
    )

    RECENT_ISSUE_STATE_ROW_COUNT.observe(len(rows))
    # Truncating instead would leave is_present false for the dropped issues, which tells the query
    # they did not change and makes it use their stale ClickHouse state. Discard the whole overlay so
    # that every issue falls back to ClickHouse together.
    if len(rows) > MAX_RECENT_ISSUE_STATES:
        return []

    return [
        RecentIssueState(
            team_id=team_id,
            issue_id=row["id"],
            issue_status=row["status"],
            issue_severity=row["severity"],
            issue_name=row["name"],
            issue_description=row["description"],
            assigned_user_id=row["assignment__user_id"],
            assigned_role_id=row["assignment__role_id"],
        )
        for row in rows
    ]
