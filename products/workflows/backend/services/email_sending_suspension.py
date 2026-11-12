"""Staff suspension of a team's workflow email sending, with the audit row and the messages to the team."""

import dataclasses

import structlog

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.team import Team
from posthog.models.user import User
from posthog.tasks.email import send_email_sending_suspended, send_email_sending_unsuspended

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.workflows.backend.facade.contracts import EmailSendingSuspensionChange
from products.workflows.backend.services import email_sending_controls

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class EmailSendingSuspensionActivityContext(ActivityContextBase):
    reason: str


def _log_activity(team: Team, activity: str, reason: str, user_id: int | None, was_impersonated: bool) -> None:
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=User.objects.filter(pk=user_id).first() if user_id is not None else None,
        was_impersonated=was_impersonated,
        item_id=team.pk,
        scope="Team",
        activity=activity,
        detail=Detail(
            name=team.name,
            type="admin_email_sending_suspension",
            context=EmailSendingSuspensionActivityContext(reason=reason),
        ),
    )


def _notify_in_app(team_id: int, suspended: bool, reason: str) -> None:
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.EMAIL_REPUTATION,
            priority=Priority.CRITICAL if suspended else Priority.NORMAL,
            title=(
                "Email sending has been suspended for this project"
                if suspended
                else "Email sending has been re-enabled for this project"
            ),
            body=(
                f"Reason: {reason}. Check the Reputation tab and contact support to get sending re-enabled."
                if suspended
                else "Your workflows can deliver email again. Keep bounce and complaint rates low to stay enabled."
            ),
            target_type=TargetType.TEAM,
            target_id=str(team_id),
            source_url="/workflows/reputation",
        )
    )


def suspend_email_sending(
    team_id: int, reason: str, *, user_id: int | None = None, was_impersonated: bool = False
) -> EmailSendingSuspensionChange:
    """Suspend the team's workflow email, write the audit row, and tell the team by email and in the app.

    Does nothing when the team is already suspended, so a double submit sends the team one message.
    """
    change = email_sending_controls.suspend_email_sending(
        team_id, reason, user_id=user_id, was_impersonated=was_impersonated
    )
    if change.changed_at is None:
        return change
    team = Team.objects.get(pk=team_id)
    logger.info("staff_suspend_email_sending", team_id=team_id, reason=reason, user_id=user_id)
    _log_activity(team, "email_sending_suspended", reason, user_id, was_impersonated)
    # The suspension already committed, and a retry would find the team suspended and skip the messages.
    # So a failure here is reported to the caller instead of raised.
    try:
        send_email_sending_suspended.delay(team_id=team_id, reason=reason, suspended_at=change.changed_at.isoformat())
        _notify_in_app(team_id, suspended=True, reason=reason)
    except Exception:
        logger.exception("staff_suspend_email_sending_notify_failed", team_id=team_id)
        return dataclasses.replace(change, notification_failed=True)
    return change


def unsuspend_email_sending(
    team_id: int, *, user_id: int | None = None, was_impersonated: bool = False
) -> EmailSendingSuspensionChange:
    """Re-enable the team's workflow email, write the audit row, and tell the team by email and in the app."""
    change = email_sending_controls.unsuspend_email_sending(team_id)
    if change.changed_at is None:
        return change
    team = Team.objects.get(pk=team_id)
    logger.info("staff_unsuspend_email_sending", team_id=team_id, user_id=user_id)
    _log_activity(team, "email_sending_unsuspended", "", user_id, was_impersonated)
    try:
        send_email_sending_unsuspended.delay(team_id=team_id, unsuspended_at=change.changed_at.isoformat())
        _notify_in_app(team_id, suspended=False, reason="")
    except Exception:
        logger.exception("staff_unsuspend_email_sending_notify_failed", team_id=team_id)
        return dataclasses.replace(change, notification_failed=True)
    return change
