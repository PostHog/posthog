"""Send each settled Inbox report to the project's real-time destinations.

Write one `$inbox_report_ready` internal event per report and let each destination's filters decide
whether it wants it. The CDP internal-events consumer evaluates that, so nothing here needs to know a
destination exists.

Delivery is at least once. The claim on the report keeps a re-settle from sending it again, and the
reconcile sweep re-sends a claim the broker never confirmed, with the same event uuid. A first event
that went through late, or a Kafka redelivery, can therefore reach a destination twice. Receivers
dedupe on `report_id`.
"""

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

# Fixed namespace so a report always maps to the same event uuid, whichever producer settled it.
_INBOX_REPORT_EVENT_NAMESPACE = uuid.UUID("0b5e7c1a-4f3d-4e8b-9a2c-6d1f8e3b7a90")

_DELIVERY_TIMEOUT_SECONDS = 10

# Far above the delivery timeout, so the sweep never races a publish that is still in flight.
_STALE_CLAIM_AGE = timedelta(minutes=15)
_RECONCILE_BATCH_SIZE = 200
# Well under the sweep task's 270 s soft time limit, so the last batch still has time to flush and confirm.
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


def emit_inbox_report_ready_event(*, team_id: int, report_id: str, source_products: list[str]) -> None:
    """Send the report out once, the first time it settles as ready, together with the layers of its plan.

    A layer is born ready in the transaction that settles its plan and runs no workflow of its own,
    so this is the only point that sends it. A report the Inbox hides, because the scout that wrote
    it turned its Inbox destination off, is not sent.

    Waits for the broker to accept the events. An event the broker rejects or never confirms keeps
    its claim unconfirmed, and `reconcile_stranded_ready_events` sends it again once the claim goes
    stale. Never raises: a producer calls this after the report is already committed, and a
    delivery problem must not fail the report that settled. A caller that can retry calls
    `send_inbox_report_ready_events` instead.
    """
    try:
        send_inbox_report_ready_events(team_id=team_id, report_id=report_id, source_products=source_products)
    except Exception:
        logger.exception("inbox_report_ready_event_failed", team_id=team_id, report_id=report_id)


def send_inbox_report_ready_events(*, team_id: int, report_id: str, source_products: list[str]) -> None:
    """`emit_inbox_report_ready_event`, except that a failure before the claims are written raises.

    Nothing records a report that was never claimed, so only the caller's retry can still send it.
    Once claimed, a report is the sweep's to send again. A project whose flag could not be evaluated
    gets its reports claimed but not sent, so the sweep sends them once the flag answers.
    """
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
    """The project's flag, or None when it could not be evaluated.

    Fails closed: a flag-service error must not start sending a project's reports off-platform.
    """
    if settings.DEBUG:
        return True
    if posthoganalytics.disabled:
        # An instance that opted out of PostHog's own analytics never gets an answer, so the flag is off for good.
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
    """Send the event again for each stale claim the broker never confirmed.

    A delivery still pending after the flush, or a worker that died between the claim and the
    publish, leaves such a claim. Works through the claims batch by batch until none is left or the
    time budget runs out. A project whose flag is off, or a report its scout has since hidden from
    the Inbox, gets its claim back unsent, so they stop retries as well as first sends. A project
    whose flag could not be evaluated keeps its claims for a later sweep.
    """
    deadline = time.monotonic() + _SWEEP_TIME_BUDGET.total_seconds()
    while True:
        stranded = _stranded_claims()
        flags: dict[int, bool | None] = {}
        renewed: list[_ReadyEventClaim] = []
        for claim, claimed_at in stranded:
            if claim.team_id not in flags:
                # Each project's flag check can wait on the flag service, so stop before the time limit
                # and leave the rest of the batch stale for the next sweep.
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
        # A short batch was the last one. Stopping there also keeps a claim that could be neither
        # renewed nor released from being re-read until the deadline.
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
    """Produce every event, wait for the broker once, then confirm each event it accepted.

    A failed or unconfirmed event keeps its claim, so the sweep sends it again later.
    """
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
        # The producer still holds the event and keeps retrying it, so only the sweep sends it again.
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
    """Take the claim over for a retry, or give it back when the report is no longer ready or its project's flag is off.

    With the flag unknown, the claim is renewed without a send, so it waits for a later sweep at the
    back of the queue instead of holding up other projects' claims.
    """
    if destinations_enabled is None:
        _stale_claim(team_id, report_id, claimed_at).update(ready_event_emitted_at=timezone.now())
        return False
    if destinations_enabled and _stale_claim(team_id, report_id, claimed_at).filter(
        status=SignalReport.Status.READY
    ).update(ready_event_emitted_at=timezone.now()):
        return True
    released = _stale_claim(team_id, report_id, claimed_at)
    if destinations_enabled:
        # A report that settled after the renew skipped its own emit on this claim, so the next sweep sends it.
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
