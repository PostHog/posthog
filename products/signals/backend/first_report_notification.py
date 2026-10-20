from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.cloud_utils import is_cloud
from posthog.models import Team
from posthog.transactional_email import (
    TransactionalEmailRejected,
    TransactionalEmailRetryableError,
    is_transactional_email_configured,
    send_transactional_email,
)
from posthog.utils import absolute_uri

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.models import SignalFirstReportNotification, SignalReport
from products.signals.backend.report_access import may_read_reports

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from posthog.models import User

logger = structlog.get_logger(__name__)


def register_first_report_notification(*, team: Team, user: User) -> None:
    SignalFirstReportNotification.objects.for_team(team.id).get_or_create(
        team_id=team.id, defaults={"activated_by": user}
    )


def _eligible_recipient(user: User | None, team: Team) -> bool:
    return bool(
        user
        and user.is_active
        and user.email
        and user.distinct_id
        and team.organization.members.filter(pk=user.pk).exists()
        and may_read_reports(user=user, team=team)
    )


def _visible_reports(team_id: int) -> QuerySet[SignalReport]:
    return (
        SignalReport.objects.filter(
            team_id=team_id,
            status=SignalReport.Status.READY,
            latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
            latest_already_addressed=False,
        )
        .exclude(title="")
        .exclude(summary="")
    )


def _claim(team_id: int) -> SignalFirstReportNotification | None:
    with transaction.atomic():
        notification = (
            SignalFirstReportNotification.objects.for_team(team_id)
            .select_for_update(of=("self",))
            .select_related("team__organization", "activated_by")
            .filter(queued_at__isnull=True, cancelled_at__isnull=True, send_started_at__isnull=True)
            .first()
        )
        if notification is None:
            return None
        if not _eligible_recipient(notification.activated_by, notification.team):
            notification.cancelled_at = timezone.now()
            notification.save(update_fields=["cancelled_at"])
            return None
        reports = _visible_reports(team_id).filter(first_visible_at__gte=notification.activated_at)
        if notification.message_data:
            report = reports.filter(id=notification.report_id).first() if notification.report_id else None
        else:
            report = reports.order_by("first_visible_at", "id").first()
        if report is None:
            if notification.message_data:
                notification.cancelled_at = timezone.now()
                notification.save(update_fields=["cancelled_at"])
            return None
        if notification.report_id is None:
            notification.report = report
            notification.message_data = {
                "project_id": team_id,
                "report_id": str(report.id),
                "report_title": report.title,
                "report_url": absolute_uri(f"/project/{team_id}/inbox/reports/{report.id}"),
                "activation_id": str(notification.id),
            }
        # The transactional API has no idempotency key. A crash or uncertain response must leave
        # this marker intact, because another send could duplicate an email already queued.
        notification.send_started_at = timezone.now()
        notification.last_error = ""
        notification.save(update_fields=["report", "message_data", "send_started_at", "last_error"])
        return notification


def deliver_first_report_email(team_id: int) -> None:
    if not is_cloud() or not is_transactional_email_configured() or not settings.SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID:
        return
    notification = _claim(team_id)
    if notification is None:
        return
    assert notification.activated_by is not None
    record = SignalFirstReportNotification.objects.for_team(team_id).filter(pk=notification.pk)
    try:
        message_id = send_transactional_email(
            settings.SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID,
            to=notification.activated_by.email,
            distinct_id=str(notification.activated_by.distinct_id),
            message_data=notification.message_data,
        )
    except (TransactionalEmailRetryableError, TransactionalEmailRejected, ImproperlyConfigured) as error:
        # These failures occur before the workflow accepts a send, so they can safely retry.
        record.update(
            send_started_at=None, last_error="setup_error" if isinstance(error, ImproperlyConfigured) else str(error)
        )
        raise
    except Exception:
        record.update(last_error="delivery_uncertain")
        logger.exception("first_report_email_delivery_uncertain", notification_id=str(notification.id))
        raise
    record.update(queued_at=timezone.now(), message_id=message_id)
