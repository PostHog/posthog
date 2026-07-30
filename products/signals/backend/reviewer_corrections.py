"""Human corrections to report reviewer lists, read from the activity log.

A human swapping a report's suggested reviewers is the strongest ownership precedent
the product records, so both agentic surfaces route by it: the scout project profile
(`scout_harness/profile/builders.py`) and the report-research reviewers turn
(`report_generation/research.py`). This module is the single reader so the two
surfaces can never disagree on what counts as a correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityLog

# Human reviewer corrections are rare and precious routing precedent, so the window is
# much longer than the scout profile's general activity aggregate. 90d keeps a quarter
# of corrections available without an activity-log drill-down (which is premium-gated
# on cloud, unlike this ORM read).
REVIEWER_CORRECTIONS_WINDOW_DAYS = 90
REVIEWER_CORRECTIONS_LIMIT = 20


@dataclass(frozen=True)
class ReviewerCorrection:
    """One human edit to a report's suggested reviewers: login lists before and after."""

    report_id: str
    report_title: str | None
    before: list[str]
    after: list[str]
    at: str | None


def recent_reviewer_corrections(
    team_id: int,
    *,
    window_days: int = REVIEWER_CORRECTIONS_WINDOW_DAYS,
    limit: int = REVIEWER_CORRECTIONS_LIMIT,
) -> list[ReviewerCorrection]:
    """Recent human edits to report reviewer lists, newest first.

    An ORM read, deliberately not the activity-log API (premium-gated on cloud), so
    every caller sees corrections regardless of the org's plan. The impersonation/system
    filter matches the partial index `idx_alog_team_scp_act_crtd` (both flags required
    False) and keeps support-staff edits out of the team's routing precedent; the write
    path records `was_impersonated`, so such rows do exist.
    """
    cutoff = timezone.now() - timedelta(days=window_days)
    rows = ActivityLog.objects.filter(
        team_id=team_id,
        scope="SignalReport",
        activity="suggested_reviewers_changed",
        created_at__gte=cutoff,
        was_impersonated=False,
        is_system=False,
    ).order_by("-created_at")[:limit]

    corrections: list[ReviewerCorrection] = []
    for row in rows:
        detail = row.detail or {}
        changes = detail.get("changes") or []
        change = changes[0] if changes and isinstance(changes[0], dict) else {}
        corrections.append(
            ReviewerCorrection(
                report_id=str(row.item_id),
                report_title=detail.get("name"),
                before=list(change.get("before") or []),
                after=list(change.get("after") or []),
                at=row.created_at.isoformat() if row.created_at else None,
            )
        )
    return corrections
