import structlog
import posthoganalytics
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.models.scoping import with_team_scope

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports

logger = structlog.get_logger(__name__)

RUN_FINISHED_NOTICES_FLAG = "inbox-run-finished-notices"
# NotificationEvent.title is a varchar(255).
_TITLE_LIMIT = 255

# An interactive run reports each finished turn, so the first one counts as the run finishing.
_OUTCOMES = {
    "completed": "finished",
    "turn_completed": "finished",
    "failed": "failed",
    "cancelled": "was cancelled",
}


def run_finished_title(report_title: str | None, kind: str) -> str:
    title = f'The run for "{report_title or "Untitled report"}" {_OUTCOMES[kind]}'
    return title if len(title) <= _TITLE_LIMIT else title[: _TITLE_LIMIT - 1] + "…"


def notify_run_finished(*, report: SignalReport, task_run_id: str, kind: str, recipient_id: int) -> None:
    """Queue the bell notification for the person who started an implementation run that ended."""
    if kind not in _OUTCOMES:
        return
    try:
        # Delivery evaluates a remote flag, so the run's status write must not wait on it.
        send_run_finished_notification.delay(
            team_id=report.team_id,
            report_id=str(report.id),
            recipient_id=recipient_id,
            task_run_id=task_run_id,
            kind=kind,
        )
    except Exception as error:
        capture_exception(error)


def _flag_enabled(team: Team) -> bool:
    org_id = str(team.organization_id)
    try:
        return (
            posthoganalytics.feature_enabled(
                RUN_FINISHED_NOTICES_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
            )
            is True
        )
    except Exception:
        logger.warning("run_finished_notices_flag_check_failed", exc_info=True)
        return False


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
@with_team_scope()
def send_run_finished_notification(
    team_id: int, report_id: str, recipient_id: int, task_run_id: str, kind: str
) -> None:
    team = Team.objects.filter(id=team_id).first()
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).only("id", "team_id", "title").first()
    recipient = User.objects.filter(id=recipient_id, is_active=True).first()
    if team is None or report is None or recipient is None or not _flag_enabled(team):
        return
    # The notification carries the report title, so a recipient who lost Inbox access must not get it.
    if not may_read_reports(user=recipient, team=team):
        return
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.REPORT_RUN_FINISHED,
            title=run_finished_title(report.title, kind),
            body="",
            target_type=TargetType.USER,
            target_id=str(recipient_id),
            resource_id=report_id,
            source_url=f"/project/{team_id}/inbox/reports/{report_id}",
            # One notice per run and outcome, whether the run ends as a whole or a turn at a time.
            idempotency_key=f"report-run-finished:{task_run_id}:{'completed' if kind == 'turn_completed' else kind}",
        )
    )
