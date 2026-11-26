"""Report reads for surfaces outside signals that show or announce a single report."""

from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.error_tracking_reports import reports_referencing_known_issue
from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.scout_authorship import inbox_hidden_report_filter, report_is_hidden_from_inbox

__all__ = [
    "ReportCard",
    "get_report_card",
    "inbox_report_ids_for_error_tracking_issue",
    "may_read_reports",
    "user_may_receive_report_push",
]


@frozen
class ReportCard:
    title: str | None
    status: str
    signal_count: int
    updated_at: datetime


def get_report_card(*, team_id: int, report_id: str) -> ReportCard | None:
    """The report's preview fields, or ``None`` when the team has no such report or it is deleted."""
    report = (
        SignalReport.objects.filter(team_id=team_id, pk=report_id).exclude(status=SignalReport.Status.DELETED).first()
    )
    if report is None:
        return None
    return ReportCard(
        title=report.title,
        status=report.status,
        signal_count=report.signal_count,
        updated_at=report.updated_at,
    )


def user_may_receive_report_push(*, user: User, team_id: int | str, report_id: str) -> bool:
    """Whether the user may still get a push notification about the report.

    The report must be visible in the inbox, and the user must be an active member of its
    organization with access to the project and to reports.
    """
    report = (
        SignalReport.objects.filter(team_id=team_id, id=report_id)
        .exclude(status__in=[SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED])
        .select_related("team")
        .first()
    )
    return bool(
        report
        and not report_is_hidden_from_inbox(report.team_id, str(report.id))
        and User.objects.filter(
            id=user.id,
            is_active=True,
            organization_membership__organization_id=report.team.organization_id,
        ).exists()
        and UserAccessControl(user=user, team=report.team).has_project_access
        and may_read_reports(user=user, team=report.team)
    )


INBOX_REPORT_IDS_LIMIT = 10


def inbox_report_ids_for_error_tracking_issue(
    *, team: Team, issue_id: UUID, max_execution_time: int | None = None
) -> list[str]:
    """Ids of the inbox reports that reference an error tracking issue, most recently updated first.

    The caller must already have loaded the issue for this team. The ids are the reports the inbox
    list shows: suppressed and deleted reports, and reports a scout kept out of the inbox, are left out.
    """
    report_ids = reports_referencing_known_issue(team=team, issue_id=issue_id, max_execution_time=max_execution_time)
    if not report_ids:
        return []
    return [
        str(report_id)
        for report_id in SignalReport.objects.filter(team_id=team.id, id__in=report_ids)
        .exclude(status__in=[SignalReport.Status.SUPPRESSED, SignalReport.Status.DELETED])
        .filter(inbox_hidden_report_filter(team.id))
        .order_by("-updated_at", "id")
        .values_list("id", flat=True)[:INBOX_REPORT_IDS_LIMIT]
    ]
