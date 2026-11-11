import time
import uuid
from datetime import datetime, timedelta
from typing import TypedDict

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from celery.exceptions import SoftTimeLimitExceeded
from posthoganalytics import feature_enabled

from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult
from posthog.models.team.team import Team

from products.cdp.backend.internal_events import (
    INBOX_REPORT_READY_EVENT,
    InternalEventEvent,
    flush_internal_events_producer,
    produce_internal_event,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.priority import persisted_report_priority
from products.signals.backend.report_urls import ReportLinkSource, build_report_url
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox
from products.signals.backend.typed_report_links import incoming_links

logger = structlog.get_logger(__name__)

INBOX_REPORT_DESTINATIONS_FLAG = "inbox-report-destinations"

_INBOX_REPORT_EVENT_NAMESPACE = uuid.UUID("0b5e7c1a-4f3d-4e8b-9a2c-6d1f8e3b7a90")

_DELIVERY_TIMEOUT_SECONDS = 10
_RETRY_DELAY_SECONDS = 60

_STALE_CLAIM_AGE = timedelta(minutes=15)
_RECONCILE_BATCH_SIZE = 200
_SWEEP_TIME_BUDGET = timedelta(minutes=3)


class InboxReportReadyProperties(TypedDict):
    report_id: str
    title: str | None
    summary: str | None
    priority: str | None
    source_products: list[str]
    report_url: str


@frozen
class _ReadyEventClaim:
    team_id: int
    report_id: str
    source_products: list[str]


def emit_inbox_report_ready_event(*, team_id: int, report_id: str, source_products: list[str]) -> bool:
    try:
        send_inbox_report_ready_events(team_id=team_id, report_id=report_id, source_products=source_products)
    except Exception:
        logger.exception("inbox_report_ready_event_failed", team_id=team_id, report_id=report_id)
        return _schedule_retry(team_id=team_id, report_id=report_id, source_products=source_products)
    return True


def _schedule_retry(*, team_id: int, report_id: str, source_products: list[str]) -> bool:
    from products.signals.backend.tasks import retry_inbox_report_ready_event  # noqa: PLC0415

    try:
        retry_inbox_report_ready_event.apply_async(
            kwargs={"team_id": team_id, "report_id": report_id, "source_products": source_products},
            countdown=_RETRY_DELAY_SECONDS,
        )
    except Exception:
        logger.exception("inbox_report_ready_event_retry_not_scheduled", team_id=team_id, report_id=report_id)
        return False
    return True


def send_inbox_report_ready_events(*, team_id: int, report_id: str, source_products: list[str]) -> None:
    destinations_enabled = _destinations_flag(team_id)
    if destinations_enabled is False or report_is_hidden_from_inbox(team_id, report_id):
        return
    claims = [
        _ReadyEventClaim(team_id=team_id, report_id=claimed_id, source_products=source_products)
        for claimed_id in [report_id, *_plan_layer_ids(team_id, report_id)]
        if _claim_ready_event(team_id, claimed_id, source_products)
    ]
    if destinations_enabled:
        _publish_ready_events(claims)


def _destinations_flag(team_id: int) -> bool | None:
    if settings.DEBUG:
        return True
    if posthoganalytics.disabled:
        return False
    try:
        organization_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        enabled = feature_enabled(
            INBOX_REPORT_DESTINATIONS_FLAG,
            str(organization_id),
            groups={"organization": str(organization_id), "project": str(team_id)},
            group_properties={"organization": {"id": str(organization_id)}, "project": {"id": str(team_id)}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("inbox_report_destinations_flag_check_failed", team_id=team_id, exc_info=True)
        return None
    return None if enabled is None else enabled is True


def reconcile_stranded_ready_events() -> None:
    deadline = time.monotonic() + _SWEEP_TIME_BUDGET.total_seconds()
    while True:
        stranded = _stranded_claims()
        flags: dict[int, bool | None] = {}
        renewed: list[_ReadyEventClaim] = []
        for claim, claimed_at in stranded:
            if claim.team_id not in flags:
                if time.monotonic() >= deadline:
                    break
                flags[claim.team_id] = _destinations_flag(claim.team_id)
            destinations_enabled = flags[claim.team_id]
            if destinations_enabled and report_is_hidden_from_inbox(claim.team_id, claim.report_id):
                destinations_enabled = False
            if _renew_stale_claim(
                claim.team_id, claim.report_id, claimed_at, destinations_enabled=destinations_enabled
            ):
                renewed.append(claim)
        _publish_ready_events(renewed)
        if len(stranded) < _RECONCILE_BATCH_SIZE or time.monotonic() >= deadline:
            return


def _stranded_claims() -> list[tuple[_ReadyEventClaim, datetime]]:
    stale_before = timezone.now() - _STALE_CLAIM_AGE
    stranded = (
        SignalReport.objects.filter(ready_event_emitted_at__lt=stale_before, ready_event_delivered_at__isnull=True)
        .order_by("ready_event_emitted_at")
        .values_list("team_id", "id", "ready_event_emitted_at", "ready_event_source_products")[:_RECONCILE_BATCH_SIZE]
    )
    return [
        (
            _ReadyEventClaim(team_id=team_id, report_id=str(report_id), source_products=source_products or []),
            claimed_at,
        )
        for team_id, report_id, claimed_at, source_products in stranded
        if claimed_at is not None
    ]


def _publish_ready_events(claims: list[_ReadyEventClaim]) -> None:
    produced = [(claim, delivery) for claim in claims if (delivery := _produce_ready_event(claim)) is not None]
    if not produced:
        return
    try:
        flush_internal_events_producer(_DELIVERY_TIMEOUT_SECONDS)
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("inbox_report_ready_event_flush_failed", report_count=len(produced))
        return
    for claim, delivery in produced:
        _confirm_delivery(claim, delivery)


def _produce_ready_event(claim: _ReadyEventClaim) -> ProduceResult | None:
    try:
        return produce_internal_event(
            claim.team_id,
            InternalEventEvent(
                event=INBOX_REPORT_READY_EVENT,
                distinct_id=claim.report_id,
                properties=dict(_event_properties(claim.team_id, claim.report_id, claim.source_products)),
                uuid=str(uuid.uuid5(_INBOX_REPORT_EVENT_NAMESPACE, f"{claim.team_id}:{claim.report_id}")),
            ),
        )
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("inbox_report_ready_event_failed", team_id=claim.team_id, report_id=claim.report_id)
        return None


def _confirm_delivery(claim: _ReadyEventClaim, delivery: ProduceResult) -> None:
    try:
        delivery.get(timeout=0)
    except TimeoutError:
        logger.warning("inbox_report_ready_event_delivery_pending", team_id=claim.team_id, report_id=claim.report_id)
        return
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("inbox_report_ready_event_failed", team_id=claim.team_id, report_id=claim.report_id)
        return
    SignalReport.objects.filter(id=claim.report_id, team_id=claim.team_id).update(
        ready_event_delivered_at=timezone.now()
    )


def _claim_ready_event(team_id: int, report_id: str, source_products: list[str]) -> bool:
    if report_is_hidden_from_inbox(team_id, report_id):
        return False
    return bool(
        SignalReport.objects.filter(
            id=report_id, team_id=team_id, status=SignalReport.Status.READY, ready_event_emitted_at__isnull=True
        ).update(ready_event_emitted_at=timezone.now(), ready_event_source_products=source_products)
    )


def _plan_layer_ids(team_id: int, report_id: str) -> list[str]:
    return [
        edge.source_id for edge in incoming_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.PART_OF,))
    ]


def _renew_stale_claim(
    team_id: int, report_id: str, claimed_at: datetime, *, destinations_enabled: bool | None
) -> bool:
    if destinations_enabled is None:
        _stale_claim(team_id, report_id, claimed_at).update(ready_event_emitted_at=timezone.now())
        return False
    if destinations_enabled and _stale_claim(team_id, report_id, claimed_at).filter(
        status=SignalReport.Status.READY
    ).update(ready_event_emitted_at=timezone.now()):
        return True
    released = _stale_claim(team_id, report_id, claimed_at)
    if destinations_enabled:
        released = released.exclude(status=SignalReport.Status.READY)
    released.update(ready_event_emitted_at=None, ready_event_source_products=None)
    return False


def _stale_claim(team_id: int, report_id: str, claimed_at: datetime) -> QuerySet[SignalReport]:
    return SignalReport.objects.filter(
        id=report_id, team_id=team_id, ready_event_emitted_at=claimed_at, ready_event_delivered_at__isnull=True
    )


def _event_properties(team_id: int, report_id: str, source_products: list[str]) -> InboxReportReadyProperties:
    report = SignalReport.objects.only("title", "summary").get(id=report_id, team_id=team_id)
    priority = persisted_report_priority(team_id=team_id, report_id=report_id, before=timezone.now())
    return InboxReportReadyProperties(
        report_id=report_id,
        title=report.title,
        summary=report.summary,
        priority=priority.value if priority is not None else None,
        source_products=source_products,
        report_url=build_report_url(team_id, report_id, ReportLinkSource.DESTINATION),
    )
