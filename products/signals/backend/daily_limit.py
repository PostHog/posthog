"""Per-team daily report limit enforcement.

Sibling of `quota.py` (the org-level billing quota gate) with the same fail-open posture, but a
separate module because this gate needs the signals models: `quota.py` sits on the
`billing.py` <- `posthog.tasks.usage_report` <- `ee.billing.quota_limiting` early-import path and
must stay model-free, while nothing on that path imports this module.

The limit is `SignalTeamConfig.max_reports_per_day` (null = unlimited). A report consumes the
limit when it first becomes user-visible, which `SignalReport.first_visible_at` records; "today"
is the project-timezone calendar day. There is no enforcement flag: setting the field is the
opt-in.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity

from posthog.event_usage import groups
from posthog.temporal.common.metrics import get_metric_meter

from products.signals.backend.models import SignalReport, SignalTeamConfig

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class DailyReportLimitGate:
    """One pipeline gate decision: `limited` is whether the gate should block; `limit` and
    `reports_today` carry the numbers for telemetry (both meaningless when no limit is set)."""

    limited: bool
    limit: int | None
    reports_today: int


def record_daily_limit_check_failed_open() -> None:
    """Count a daily-limit check that errored and failed open (no-op outside a Temporal
    activity). Keeps the bypass alertable, mirroring the billing quota's fail-open counter."""
    # Emit the meter directly rather than via products.signals.backend.temporal.metrics: importing
    # that package runs its __init__, which imports buffer.py, which imports this module (cycle).
    if not activity.in_activity():
        return
    get_metric_meter().create_counter(
        "signals_daily_limit_check_failed_open_total",
        "Signals daily report limit checks that errored and failed open, bypassing enforcement",
    ).add(1)


def team_day_start(team: "Team", at: datetime | None = None) -> datetime:
    """Midnight of the current calendar day in the project's timezone, as an aware datetime.

    The billing quota's `posthog.utils.get_current_day` is hardcoded to UTC; this limit is a
    user-experience cap ("reports I got today"), so the day follows `team.timezone_info` instead.
    On a spring-forward day where local midnight doesn't exist, ZoneInfo resolves the nonexistent
    time deterministically, so the boundary shifts by at most the DST gap.
    """
    local = (at or timezone.now()).astimezone(team.timezone_info)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def reports_generated_today(team: "Team", *, day_start: datetime) -> int:
    """How many reports first became user-visible since `day_start`.

    Counts `first_visible_at` stamps (set once, on the first transition into READY or
    PENDING_INPUT), so re-research of an already-visible report never recounts.
    """
    return SignalReport.objects.filter(team_id=team.id, first_visible_at__gte=day_start).count()


def daily_report_limit_gate(team: "Team") -> DailyReportLimitGate:
    """Resolve the daily report limit gate for one team.

    Teams without a configured limit return immediately without running the count query, so the
    fleet-wide hot paths (every buffer flush, every gate check) pay a single indexed limit read.
    Fails open on any error: an infra blip lets work through rather than stalling the pipeline.
    Blocking database I/O; wrap in `sync_to_async`/`database_sync_to_async` from async code.
    """
    try:
        limit = SignalTeamConfig.objects.filter(team_id=team.id).values_list("max_reports_per_day", flat=True).first()
        if limit is None:
            return DailyReportLimitGate(limited=False, limit=None, reports_today=0)
        reports_today = reports_generated_today(team, day_start=team_day_start(team))
        return DailyReportLimitGate(limited=reports_today >= limit, limit=limit, reports_today=reports_today)
    except Exception:
        logger.warning("signals_daily_limit_check_failed_open", team_id=team.id, exc_info=True)
        record_daily_limit_check_failed_open()
        return DailyReportLimitGate(limited=False, limit=None, reports_today=0)


def capture_signal_report_daily_limit_paused(
    team: "Team", *, report_id: str | None, stage: str, gate: DailyReportLimitGate
) -> None:
    """`signal_report_daily_limit_paused`: a pipeline gate paused work because the team hit its
    daily report limit at `stage`. No `enforced` property, unlike the billing event: the field
    being set is the enforcement switch, so every event is a real block. Best-effort: telemetry
    must never fail the pipeline step that emitted it. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signal_report_daily_limit_paused",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "report_id": report_id,
                "stage": stage,
                "limit": gate.limit,
                "reports_today": gate.reports_today,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception(
            "Failed to capture signal_report_daily_limit_paused", report_id=report_id, team_id=team.id, stage=stage
        )
