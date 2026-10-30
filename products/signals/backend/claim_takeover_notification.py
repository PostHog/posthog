from posthog.exceptions_capture import capture_exception

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import SignalReport
from products.signals.backend.report_claims import ReportClaim


def notify_claim_taken_over(*, report: SignalReport, previous: ReportClaim, actor: ArtefactAttribution) -> None:
    if previous.actor_user_id is None:
        return
    try:
        create_notification(
            NotificationData(
                team_id=report.team_id,
                notification_type=NotificationType.REPORT_CLAIM_TAKEN_OVER,
                title=f"{claim_display_name(report, actor)} took over a report you were working on",
                body=report.title or "",
                target_type=TargetType.USER,
                target_id=str(previous.actor_user_id),
                source_url=f"/project/{report.team_id}/inbox/reports/{report.id}",
                idempotency_key=f"report-claim-taken-over:{previous.claim_id}",
            )
        )
    except Exception as error:
        capture_exception(error)
