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
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_claims import ReportClaim

_TITLE_SUFFIX = " took over a report you were working on"
# NotificationEvent.title is a varchar(255), and an MCP client name alone can run to 200 characters.
_DISPLAY_NAME_LIMIT = 255 - len(_TITLE_SUFFIX)


def _takeover_title(display_name: str) -> str:
    # Cut by raw length: Django's Truncator skips combining marks when it counts, so a name built from them
    # could still overflow the column and fail every delivery attempt.
    if len(display_name) > _DISPLAY_NAME_LIMIT:
        display_name = display_name[: _DISPLAY_NAME_LIMIT - 1] + "…"
    return f"{display_name}{_TITLE_SUFFIX}"


def notify_claim_taken_over(*, report: SignalReport, previous: ReportClaim, actor: ArtefactAttribution) -> None:
    """Queue the notification for the person whose claim was taken over. Call after the takeover commits."""
    if previous.actor_user_id is None:
        return
    try:
        # Delivery evaluates a remote flag, so a bulk takeover must not wait on it once per report.
        send_claim_takeover_notification.delay(
            team_id=report.team_id,
            report_id=str(report.id),
            recipient_id=previous.actor_user_id,
            previous_claim_id=str(previous.claim_id),
            title=_takeover_title(claim_display_name(report, actor)),
        )
    except Exception as error:
        capture_exception(error)


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
@with_team_scope()
def send_claim_takeover_notification(
    team_id: int, report_id: str, recipient_id: int, previous_claim_id: str, title: str
) -> None:
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).only("id", "team_id", "title").first()
    recipient = User.objects.filter(id=recipient_id, is_active=True).first()
    if report is None or recipient is None:
        return
    # The notification carries the report title, so a recipient who lost Inbox access must not get it.
    if not may_read_reports(user=recipient, team=Team.objects.get(id=team_id)):
        return
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.REPORT_CLAIM_TAKEN_OVER,
            title=title,
            body=report.title or "",
            target_type=TargetType.USER,
            target_id=str(recipient_id),
            # Keeps the activity panel from folding takeovers of different reports into one group.
            resource_id=report_id,
            source_url=f"/project/{team_id}/inbox/reports/{report_id}",
            idempotency_key=f"report-claim-taken-over:{previous_claim_id}",
        )
    )
