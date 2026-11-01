"""Auto-close inactive inbox signal reports after N days of no activity.

When a team configures `auto_close_inactive_after_days` on `SignalTeamConfig`, the daily sweep
transitions candidate reports (ready or pending_input) with no activity for N days to suppressed
with dismissal reason "inactive".

A report counts as active if any of the following happened within the last N days:
1. New signals arrived on the report (ClickHouse signal timestamp).
2. Human-attributed artefacts were created (notes, title/summary edits, reviews, etc.).
3. A research or analysis run completed (report.last_run_at).
4. Non-passive user actions occurred (feedback thumbs, Slack discussion). Passive actions like
   detail views and reads do not count as activity.

The sweep safely skips reports with:
- An open implementation PR.
- An active claim (user or agent).
- A running or queued task run.
- A live report that depends on this report.

Concurrency and races are handled via `select_for_update()` in an atomic transaction, ensuring
racing human edits win over automated sweep dismissals.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import posthoganalytics
import structlog

from posthog import posthog_feature_flag_client
from posthog.models.group import groups
from posthog.models.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import DISMISSAL_REASON_INACTIVE, Dismissal
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.implementation_pr import implementation_pr_report_filter
from products.signals.backend.models import (
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportTask,
    SignalTeamConfig,
)
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync
from products.signals.backend.typed_report_links import incoming_links
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

FEATURE_FLAG = "inbox-auto-close-inactive-reports"
DEFAULT_MAX_CLOSES_PER_TEAM = 500

ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
    }
)

# Artefact types that reflect deliberate human or agent progress on the report.
_ENGAGEMENT_ARTEFACT_TYPES: frozenset[str] = frozenset(
    {
        SignalReportArtefact.ArtefactType.NOTE,
        SignalReportArtefact.ArtefactType.TITLE_CHANGE,
        SignalReportArtefact.ArtefactType.SUMMARY_CHANGE,
        SignalReportArtefact.ArtefactType.CODE_REVIEW,
        SignalReportArtefact.ArtefactType.PULL_REQUEST,
        SignalReportArtefact.ArtefactType.WORK_CLAIM,
    }
)

# Actions that represent deliberate engagement, excluding passive view/read.
_ENGAGED_ACTION_TYPES: frozenset[str] = frozenset(
    {
        SignalReportAction.ActionType.FEEDBACK,
        SignalReportAction.ActionType.SLACK_DISCUSSION,
    }
)

LIVE_DEPENDENT_STATUSES: frozenset[str] = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.CANDIDATE,
    }
)


@dataclass
class TeamSweepOutcome:
    """Outcome of an inactivity sweep for a single team."""

    candidates_considered: int = 0
    closed_count: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    remaining_backlog: int = 0


def report_last_activity(report: SignalReport) -> datetime:
    """Compute the timestamp of the latest activity on a report."""
    base_ts = report.first_visible_at or report.promoted_at or report.created_at
    if base_ts is not None and timezone.is_naive(base_ts):
        base_ts = timezone.make_aware(base_ts)
    latest: datetime = base_ts or timezone.now()

    if report.last_run_at:
        run_ts = report.last_run_at
        if timezone.is_naive(run_ts):
            run_ts = timezone.make_aware(run_ts)
        latest = max(latest, run_ts)

    # Human-attributed artefacts or deliberate content edits
    latest_artefact_ts = (
        SignalReportArtefact.objects.filter(team_id=report.team_id, report_id=report.id)
        .filter(Q(created_by__isnull=False) | Q(type__in=_ENGAGEMENT_ARTEFACT_TYPES))
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if latest_artefact_ts:
        if timezone.is_naive(latest_artefact_ts):
            latest_artefact_ts = timezone.make_aware(latest_artefact_ts)
        latest = max(latest, latest_artefact_ts)

    # Recent incoming signals in ClickHouse
    try:
        signals = fetch_signals_for_report_sync(report.team, str(report.id), newest=1)
        if signals and signals[0].get("timestamp"):
            sig_ts = signals[0]["timestamp"]
            if isinstance(sig_ts, str):
                sig_ts = datetime.fromisoformat(sig_ts.replace("Z", "+00:00"))
            if sig_ts is not None:
                if timezone.is_naive(sig_ts):
                    sig_ts = timezone.make_aware(sig_ts)
                latest = max(latest, sig_ts)
    except Exception:
        logger.debug("Failed to query ClickHouse signals for report last activity", report_id=str(report.id))

    # Deliberate lightweight actions (excluding passive view/read)
    latest_action_ts = (
        SignalReportAction.objects.for_team(report.team_id)
        .filter(report_id=report.id, type__in=_ENGAGED_ACTION_TYPES)
        .order_by("-last_at")
        .values_list("last_at", flat=True)
        .first()
    )
    if latest_action_ts:
        if timezone.is_naive(latest_action_ts):
            latest_action_ts = timezone.make_aware(latest_action_ts)
        latest = max(latest, latest_action_ts)

    return latest


def check_report_skip_reason(report: SignalReport) -> str | None:
    """Check if an inactive report should be skipped from auto-closing."""
    # 1. Open implementation PR
    has_open_pr = (
        SignalReport.objects.filter(team_id=report.team_id, id=report.id)
        .filter(implementation_pr_report_filter(team_id=report.team_id, active_only=True, report_ids=[report.id]))
        .exists()
    )
    if has_open_pr:
        return "open_pr"

    # 2. Active claim
    if get_active_claim(team_id=report.team_id, report_id=report.id) is not None:
        return "active_claim"

    # 3. Running task run
    task_ids = set(
        SignalReportArtefact.objects.filter(
            team_id=report.team_id, report_id=report.id, task_id__isnull=False
        ).values_list("task_id", flat=True)
    )
    task_ids.update(
        SignalReportTask.objects.filter(team_id=report.team_id, report_id=report.id).values_list("task_id", flat=True)
    )
    task_ids.update(
        SignalReportAssignment.all_teams.filter(
            team_id=report.team_id, report_id=report.id, actor_task_id__isnull=False
        ).values_list("actor_task_id", flat=True)
    )
    if task_ids:
        has_running_task = TaskRun.objects.filter(
            team_id=report.team_id,
            task_id__in=task_ids,
            status__in=[TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS],
        ).exists()
        if has_running_task:
            return "running_task"

    # 4. Live dependent report
    edges = incoming_links(team_id=report.team_id, report_id=report.id, kinds=(ReportLinkKind.DEPENDS_ON,))
    if edges:
        source_ids = [edge.source_id for edge in edges]
        has_live_dependent = SignalReport.objects.filter(
            team_id=report.team_id,
            id__in=source_ids,
            status__in=LIVE_DEPENDENT_STATUSES,
        ).exists()
        if has_live_dependent:
            return "live_dependent"

    return None


def close_inactive_report(
    report_id: str | UUID,
    team_id: int,
    days: int,
    *,
    cutoff: datetime,
) -> tuple[bool, str | None]:
    """Atomically close an inactive report under row lock, re-verifying eligibility."""
    with transaction.atomic():
        locked_report = (
            SignalReport.objects.select_for_update()
            .filter(id=report_id, team_id=team_id)
            .first()
        )
        if locked_report is None:
            return False, "not_found"

        if locked_report.status not in ELIGIBLE_STATUSES:
            return False, "status_changed"

        # Re-verify last activity under lock
        last_activity = report_last_activity(locked_report)
        if last_activity >= cutoff:
            return False, "recent_activity"

        # Re-check skip guards under lock
        skip_reason = check_report_skip_reason(locked_report)
        if skip_reason is not None:
            return False, skip_reason

        # Transition to suppressed with inactive dismissal reason
        attribution = ArtefactAttribution.system()
        updated_fields = locked_report.transition_to(SignalReport.Status.SUPPRESSED)
        locked_report._wrote_dismissal_feedback = True  # type: ignore[attr-defined]
        locked_report._transition_actor = attribution  # type: ignore[attr-defined]
        locked_report.save(update_fields=updated_fields)

        SignalReportArtefact.append_dismissal(
            team_id=team_id,
            report_id=str(locked_report.id),
            content=Dismissal(
                state="suppressed",
                reason=DISMISSAL_REASON_INACTIVE,
                note=f"Closed after {days} days with no activity.",
                user_id=attribution.user_id,
            ),
            attribution=attribution,
        )

        logger.info(
            "Auto-closed inactive signal report",
            report_id=str(locked_report.id),
            team_id=team_id,
            days=days,
            last_activity=last_activity.isoformat(),
        )
        return True, None


def sweep_team_inactive_reports(
    team: Team,
    config: SignalTeamConfig | None = None,
    max_closes: int = DEFAULT_MAX_CLOSES_PER_TEAM,
) -> TeamSweepOutcome:
    """Run the inactive reports auto-close sweep for one team."""
    outcome = TeamSweepOutcome()

    # Feature flag check
    if not posthog_feature_flag_client.feature_enabled_or_false(
        FEATURE_FLAG, str(team.uuid), team_id=team.id
    ):
        return outcome

    if config is None:
        config = SignalTeamConfig.objects.filter(team_id=team.id).first()

    if config is None or config.auto_close_inactive_after_days is None:
        return outcome

    days = config.auto_close_inactive_after_days
    now = timezone.now()
    cutoff = now - timedelta(days=days)

    # Initial query for potential candidates: ready or pending_input reports created/visible before cutoff
    candidates_qs = (
        SignalReport.objects.filter(
            team_id=team.id,
            status__in=ELIGIBLE_STATUSES,
        )
        .filter(
            Q(first_visible_at__lt=cutoff)
            | (Q(first_visible_at__isnull=True) & Q(created_at__lt=cutoff))
        )
        .order_by("created_at")
    )

    for candidate in candidates_qs:
        outcome.candidates_considered += 1

        if outcome.closed_count >= max_closes:
            outcome.remaining_backlog += 1
            continue

        # Check activity first
        last_activity = report_last_activity(candidate)
        if last_activity >= cutoff:
            outcome.skipped_reasons["recent_activity"] += 1
            continue

        # Check skip guards
        skip_reason = check_report_skip_reason(candidate)
        if skip_reason is not None:
            outcome.skipped_reasons[skip_reason] += 1
            continue

        closed, reason = close_inactive_report(
            report_id=candidate.id,
            team_id=team.id,
            days=days,
            cutoff=cutoff,
        )
        if closed:
            outcome.closed_count += 1
        elif reason:
            outcome.skipped_reasons[reason] += 1

    # Team telemetry
    try:
        posthoganalytics.capture(
            event="signals_inbox_auto_close_sweep",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "auto_close_inactive_after_days": days,
                "candidates_considered": outcome.candidates_considered,
                "closed_count": outcome.closed_count,
                "skipped_reasons": dict(outcome.skipped_reasons),
                "remaining_backlog": outcome.remaining_backlog,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signals_inbox_auto_close_sweep", team_id=team.id)

    return outcome


def sweep_all_teams_inactive_reports(
    max_closes_per_team: int = DEFAULT_MAX_CLOSES_PER_TEAM,
) -> dict[int, TeamSweepOutcome]:
    """Run the inactive reports auto-close sweep across all configured teams."""
    configs = (
        SignalTeamConfig.objects.filter(auto_close_inactive_after_days__isnull=False)
        .select_related("team", "team__organization")
    )
    outcomes: dict[int, TeamSweepOutcome] = {}
    for config in configs:
        team = config.team
        if team is None:
            continue
        try:
            outcomes[team.id] = sweep_team_inactive_reports(
                team=team,
                config=config,
                max_closes=max_closes_per_team,
            )
        except Exception:
            logger.exception("Failed auto-close inactive reports sweep for team", team_id=team.id)

    return outcomes
