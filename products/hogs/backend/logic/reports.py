"""Reports a hog publishes into its owner's chat, and what the owner does with them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Case, Count, IntegerField, QuerySet, Value, When
from django.utils import timezone

from ..facade.enums import (
    HogMessageAuthor,
    HogReportFollowUp,
    HogReportPriority,
    HogReportStatus,
    HogStatus,
    HogWakeCause,
)
from ..models import Hog, HogReport
from . import (
    hogs as hogs_logic,
    runner,
)

MAX_EVIDENCE = 20

FOLLOW_UP_BRIEF = {
    HogReportFollowUp.IMPLEMENT: (
        "Your owner chose Implement on a report you published. Confirm the problem still holds, then make the "
        "change you proposed. Anything outside PostHog still goes through hog-propose-action first. "
        "When it is done, tell your owner with hog-say how you checked the result."
    ),
    HogReportFollowUp.INVESTIGATE: (
        "Your owner chose Investigate on a report you published. Find the root cause and change nothing. "
        "Publish what you learn as a new report with hog-report, or tell your owner with hog-say if there "
        "is nothing new."
    ),
}


def _open_first_by_priority(reports: QuerySet[HogReport]) -> QuerySet[HogReport]:
    return reports.annotate(
        closed=Case(
            When(status=HogReportStatus.OPEN.value, then=Value(0)), default=Value(1), output_field=IntegerField()
        )
    ).order_by("closed", "priority", "-created_at")


def publish_report(
    hog: Hog,
    *,
    title: str,
    summary: str,
    priority: HogReportPriority,
    impact: str,
    proposal: str,
    evidence: list[dict[str, Any]],
) -> HogReport:
    """Publishing the same title twice while the first is open returns the first, so a retry is harmless."""
    hogs_logic.mark_seen(hog)
    existing = HogReport.objects.filter(hog=hog, status=HogReportStatus.OPEN.value, title__iexact=title.strip()).first()
    if existing is not None:
        return existing
    report = HogReport.objects.create(
        team_id=hog.team_id,
        hog=hog,
        title=title.strip(),
        summary=summary,
        priority=priority.value,
        impact=impact,
        proposal=proposal,
        evidence=evidence[:MAX_EVIDENCE],
        task_run_id=hog.current_run_id,
    )
    lead = impact.strip() or summary.strip().split("\n\n")[0]
    # The text is what the chat list previews. The chat itself draws the linked report as a card.
    hogs_logic.add_message(
        hog,
        author=HogMessageAuthor.HOG,
        content=f"{priority.value.upper()} report: {report.title}\n{lead}",
        task_run_id=hog.current_run_id,
        report=report,
    )
    return report


def list_reports(*, team_id: int, user_id: int, hog_id: UUID | None = None, include_closed: bool) -> list[HogReport]:
    reports = HogReport.objects.filter(team_id=team_id, hog__created_by_id=user_id, hog__deleted=False).select_related(
        "hog"
    )
    if hog_id is not None:
        reports = reports.filter(hog_id=hog_id)
    if not include_closed:
        reports = reports.filter(status=HogReportStatus.OPEN.value)
    return list(_open_first_by_priority(reports)[:200])


def get_report(hog: Hog, report_id: UUID) -> HogReport | None:
    return HogReport.objects.filter(hog=hog, id=report_id).select_related("hog").first()


def set_verdict(report: HogReport, *, status: HogReportStatus, reason: str) -> HogReport:
    report.status = status.value
    report.verdict_reason = "" if status == HogReportStatus.OPEN else reason
    report.read_at = report.read_at or timezone.now()
    report.save(update_fields=["status", "verdict_reason", "read_at", "updated_at"])
    if status != HogReportStatus.OPEN:
        # Kept out of the chat, but in the transcript, so the hog does not publish the same thing again.
        hogs_logic.add_message(
            report.hog,
            author=HogMessageAuthor.SYSTEM,
            content=f'Your owner marked the report "{report.title}" as {status.value}'
            + (f": {reason}" if reason else "."),
            in_chat=False,
        )
    return report


def mark_report_read(report: HogReport) -> HogReport:
    if report.read_at is None:
        report.read_at = timezone.now()
        report.save(update_fields=["read_at", "updated_at"])
    return report


def follow_up(report: HogReport, *, mode: HogReportFollowUp) -> bool:
    """Wake the hog to act on its own report. Returns False when the hog could not be woken."""
    hog = report.hog
    if hog.status == HogStatus.PAUSED:
        return False
    evidence = "\n".join(f"- {item.get('description', '')} ({item.get('source', '')})" for item in report.evidence)
    trigger = (
        f"{FOLLOW_UP_BRIEF[mode]}\n\n"
        f"Report ID: {report.id}\nTitle: {report.title}\nPriority: {report.priority.upper()}\n"
        f"Impact: {report.impact}\n\nSummary:\n{report.summary}\n\nProposal:\n{report.proposal}\n\n"
        f"Evidence:\n{evidence or '(none)'}"
    )
    if not runner.wake_hog(hog, trigger=trigger, cause=HogWakeCause.REPORT):
        return False
    report.follow_up = mode.value
    report.read_at = report.read_at or timezone.now()
    report.save(update_fields=["follow_up", "read_at", "updated_at"])
    return True


def waiting_report_counts(hog_ids: list[UUID]) -> dict[UUID, int]:
    """Open reports the owner has not acted on yet, per hog. Reading a report does not count as acting."""
    rows = (
        HogReport.objects.filter(hog_id__in=hog_ids, status=HogReportStatus.OPEN.value, follow_up="")
        .values("hog_id")
        .annotate(waiting=Count("id"))
    )
    return {row["hog_id"]: row["waiting"] for row in rows}
