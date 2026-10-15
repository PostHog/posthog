"""Start a project's "Inbox report ready" workflows when one of its reports settles.

The counterpart to ``products.workflows.backend.github_workflow_events`` and
``products.slack_app.backend.slack_workflow_events``: write one internal event per report, and let
each workflow's trigger decide whether it wants it. The CDP consumer evaluates that, so nothing here
needs to know a workflow exists.
"""

import uuid
from datetime import datetime, timedelta
from typing import TypedDict

from django.utils import timezone

import structlog

from products.cdp.backend.internal_events import (
    INBOX_REPORT_READY_EVENT,
    InternalEventEvent,
    flush_internal_events_producer,
    produce_internal_event,
)
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.priority import persisted_report_priority
from products.signals.backend.report_urls import ReportLinkSource, build_report_url

logger = structlog.get_logger(__name__)

# Fixed namespace so a report always maps to the same event uuid, whichever producer settled it.
_INBOX_REPORT_EVENT_NAMESPACE = uuid.UUID("0b5e7c1a-4f3d-4e8b-9a2c-6d1f8e3b7a90")

_DELIVERY_TIMEOUT_SECONDS = 10

# Far above the delivery timeout, so the sweep never races a publish that is still in flight.
_STALE_CLAIM_AGE = timedelta(minutes=15)
# Each unconfirmed publish can hold the sweep for the whole delivery timeout.
_RECONCILE_BATCH_SIZE = 20


class InboxReportReadyProperties(TypedDict):
    report_id: str
    title: str | None
    summary: str | None
    priority: str | None
    source_products: list[str]
    report_url: str


def emit_inbox_report_ready_event(*, team_id: int, report_id: str, source_products: list[str]) -> None:
    """Write the report out once, the first time it settles as ready.

    Waits for the broker to accept the event, because the claim is what stops a second attempt.
    An event the broker rejects or never confirms keeps its claim unconfirmed, and
    `reconcile_stranded_ready_events` sends it again once the claim goes stale. A rejected event
    still raises, so the caller can log it.
    """
    if not _claim_ready_event(team_id, report_id, source_products):
        return
    _publish_ready_event(team_id, report_id, source_products)


def reconcile_stranded_ready_events() -> None:
    """Send the event again for each stale claim the broker never confirmed.

    A delivery still pending after the flush, or a worker that died between the claim and the
    publish, leaves such a claim. The retry reuses the event uuid, but a first event that did go
    through late still starts a second run.
    """
    stale_before = timezone.now() - _STALE_CLAIM_AGE
    stranded = (
        SignalReport.objects.filter(ready_event_emitted_at__lt=stale_before, ready_event_delivered_at__isnull=True)
        .order_by("ready_event_emitted_at")
        .values_list("team_id", "id", "ready_event_emitted_at", "ready_event_source_products")[:_RECONCILE_BATCH_SIZE]
    )
    for team_id, report_id, claimed_at, source_products in stranded:
        if not _renew_stale_claim(team_id, str(report_id), claimed_at):
            continue
        try:
            _publish_ready_event(team_id, str(report_id), source_products or [])
        except Exception:
            logger.exception("inbox_report_ready_event_reconcile_failed", team_id=team_id, report_id=str(report_id))


def _publish_ready_event(team_id: int, report_id: str, source_products: list[str]) -> None:
    try:
        delivery = produce_internal_event(
            team_id,
            InternalEventEvent(
                event=INBOX_REPORT_READY_EVENT,
                distinct_id=report_id,
                properties=dict(_event_properties(team_id, report_id, source_products)),
                uuid=str(uuid.uuid5(_INBOX_REPORT_EVENT_NAMESPACE, f"{team_id}:{report_id}")),
            ),
        )
        flush_internal_events_producer(_DELIVERY_TIMEOUT_SECONDS)
        delivery.get(timeout=0)
    except TimeoutError:
        # The producer still holds the event and keeps retrying it, so only the sweep sends it again.
        logger.warning("inbox_report_ready_event_delivery_pending", team_id=team_id, report_id=report_id)
        return
    SignalReport.objects.filter(id=report_id, team_id=team_id).update(ready_event_delivered_at=timezone.now())


def _claim_ready_event(team_id: int, report_id: str, source_products: list[str]) -> bool:
    return bool(
        SignalReport.objects.filter(
            id=report_id, team_id=team_id, status=SignalReport.Status.READY, ready_event_emitted_at__isnull=True
        ).update(ready_event_emitted_at=timezone.now(), ready_event_source_products=source_products)
    )


def _renew_stale_claim(team_id: int, report_id: str, claimed_at: datetime) -> bool:
    """Take the claim over for a retry, or give it back when the report is no longer ready."""
    claim = SignalReport.objects.filter(
        id=report_id, team_id=team_id, ready_event_emitted_at=claimed_at, ready_event_delivered_at__isnull=True
    )
    if claim.filter(status=SignalReport.Status.READY).update(ready_event_emitted_at=timezone.now()):
        return True
    claim.update(ready_event_emitted_at=None, ready_event_source_products=None)
    return False


def _event_properties(team_id: int, report_id: str, source_products: list[str]) -> InboxReportReadyProperties:
    report = SignalReport.objects.only("title", "summary").get(id=report_id, team_id=team_id)
    priority = persisted_report_priority(team_id=team_id, report_id=report_id, before=timezone.now())
    return InboxReportReadyProperties(
        report_id=report_id,
        title=report.title,
        summary=report.summary,
        priority=priority.value if priority is not None else None,
        source_products=source_products,
        report_url=build_report_url(team_id, report_id, ReportLinkSource.WORKFLOW),
    )
