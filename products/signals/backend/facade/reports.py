"""Report reads for surfaces outside signals that show or announce a single report."""

from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox

__all__ = [
    "ReportCard",
    "get_report_card",
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
