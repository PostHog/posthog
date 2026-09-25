from datetime import datetime, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from products.signals.backend.implementation_pr import implementation_pr_report_filter
from products.signals.backend.models import SignalReport, SignalReportAction, SignalReportArtefact
from products.signals.backend.report_claims import reports_with_active_claim


def filter_recommendations(queryset: QuerySet[SignalReport], *, team_id: int, user_id: int) -> QuerySet[SignalReport]:
    """Select work needing attention using existing judgments and claims, not a learned ranking."""
    # Only known-open PRs need review: drafts and unknown/terminal states stay in the wider queue.
    open_links = SignalReportArtefact.objects.filter(
        team_id=team_id,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
        pull_request__team_id=team_id,
        pull_request__state="open",
    ).values("report_id")
    review = Q(status=SignalReport.Status.READY) & (
        Q(id__in=open_links) | Q(assignment__team_id=team_id, assignment__pr_state="open", assignment__pr_merged=False)
    )
    decision = (
        Q(
            status__in=[SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT],
            latest_actionability_value__in=["immediately_actionable", "requires_human_input"],
        )
        & ~reports_with_active_claim(team_id=team_id)
        & ~implementation_pr_report_filter(team_id=team_id)
    )
    snoozed = SignalReportAction.objects.for_team(team_id).filter(
        user_id=user_id, type=SignalReportAction.ActionType.SNOOZE, last_at__gt=timezone.now() - timedelta(days=7)
    )
    return queryset.filter(review | decision).exclude(
        Q(latest_already_addressed_value="true") | Q(id__in=snoozed.values("report_id"))
    )


def snooze_recommendation(*, report: SignalReport, user_id: int, snoozed: bool) -> datetime | None:
    """Use the existing personal action store; shared report state and thumbs feedback stay intact."""
    rows = SignalReportAction.objects.for_team(report.team_id).filter(
        report_id=report.id, user_id=user_id, type=SignalReportAction.ActionType.SNOOZE
    )
    if not snoozed:
        rows.delete()
        return None
    now = timezone.now()
    rows.update_or_create(
        team_id=report.team_id,
        report_id=report.id,
        user_id=user_id,
        type=SignalReportAction.ActionType.SNOOZE,
        defaults={"last_at": now},
    )
    return now + timedelta(days=7)
