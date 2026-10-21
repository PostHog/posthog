from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import Truncator

import structlog

from posthog.cloud_utils import is_cloud
from posthog.models import Team
from posthog.transactional_email import (
    TransactionalEmailRejected,
    TransactionalEmailRetryableError,
    is_transactional_email_configured,
    send_transactional_email,
)

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.constants import SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID
from products.signals.backend.models import SignalFirstReportNotification, SignalReport
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_content_gates import team_first_report_email_enabled
from products.signals.backend.report_priority import latest_report_priorities
from products.signals.backend.report_urls import ReportLinkSource, build_report_url

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
        and UserAccessControl(user=user, team=team).has_project_access
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
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
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
            if notification.message_data and (
                notification.report_id is None
                or not SignalReport.objects.filter(
                    team_id=team_id,
                    id=notification.report_id,
                    status__in=[
                        SignalReport.Status.CANDIDATE,
                        SignalReport.Status.IN_PROGRESS,
                        SignalReport.Status.PENDING_INPUT,
                    ],
                ).exists()
            ):
                notification.cancelled_at = timezone.now()
                notification.save(update_fields=["cancelled_at"])
            return None
        if notification.report_id is None:
            notification.report = report
            notification.message_data = {
                "project_id": team_id,
                "report_id": str(report.id),
                "report_title": report.title,
                "report_summary": Truncator((report.summary or "").strip().split("\n", 1)[0]).chars(320),
                "report_priority": latest_report_priorities(team_id, [str(report.id)]).get(str(report.id), ""),
                "report_url": build_report_url(team_id, report.id, ReportLinkSource.FIRST_REPORT_EMAIL),
                "activation_id": str(notification.id),
            }
        # The transactional API has no idempotency key. A crash or uncertain response must leave
        # this marker intact, because another send could duplicate an email already queued.
        notification.send_started_at = timezone.now()
        notification.next_attempt_at = None
        notification.last_error = ""
        notification.save(update_fields=["report", "message_data", "send_started_at", "next_attempt_at", "last_error"])
        return notification


def deliver_first_report_email(team_id: int) -> None:
    if not is_cloud() or not is_transactional_email_configured() or not team_first_report_email_enabled(team_id):
        return
    notification = _claim(team_id)
    if notification is None:
        return
    assert notification.activated_by is not None
    record = SignalFirstReportNotification.objects.for_team(team_id).filter(pk=notification.pk)
    try:
        message_id = send_transactional_email(
            SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID,
            to=notification.activated_by.email,
            distinct_id=str(notification.activated_by.distinct_id),
            message_data=notification.message_data,
        )
    except (TransactionalEmailRetryableError, TransactionalEmailRejected, ImproperlyConfigured) as error:
        # These failures occur before the workflow accepts a send, so they can safely retry.
        retry_after = error.retry_after if isinstance(error, TransactionalEmailRetryableError) else None
        record.update(
            send_started_at=None,
            next_attempt_at=timezone.now() + timedelta(seconds=retry_after) if retry_after is not None else None,
            last_error="setup_error" if isinstance(error, ImproperlyConfigured) else str(error),
        )
        raise
    except Exception:
        record.update(last_error="delivery_uncertain")
        logger.exception("first_report_email_delivery_uncertain", notification_id=str(notification.id))
        raise
    record.update(queued_at=timezone.now(), message_id=message_id)
