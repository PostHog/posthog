"""Start a project's "Inbox report ready" workflows when one of its reports settles.

The counterpart to ``products.workflows.backend.github_workflow_events`` and
``products.slack_app.backend.slack_workflow_events``: write one internal event per report, and let
each workflow's trigger decide whether it wants it. The CDP consumer evaluates that, so nothing here
needs to know a workflow exists.
"""

import uuid

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
from products.signals.backend.signal_metadata import fetch_source_products_for_reports

logger = structlog.get_logger(__name__)

# Fixed namespace so a report always maps to the same event uuid, whichever producer settled it.
_INBOX_REPORT_EVENT_NAMESPACE = uuid.UUID("0b5e7c1a-4f3d-4e8b-9a2c-6d1f8e3b7a90")

_DELIVERY_TIMEOUT_SECONDS = 10


def emit_inbox_report_ready_event(*, team_id: int, report_id: str) -> None:
    """Write the report out once, the first time it settles as ready.

    Waits for the broker to accept the event, because the claim is what stops a second attempt.
    A failure gives the claim back and raises, so the caller can retry.
    """
    if not _claim_ready_event(team_id, report_id):
        return
    try:
        delivery = produce_internal_event(
            team_id,
            InternalEventEvent(
                event=INBOX_REPORT_READY_EVENT,
                distinct_id=report_id,
                properties=_event_properties(team_id, report_id),
                uuid=str(uuid.uuid5(_INBOX_REPORT_EVENT_NAMESPACE, f"{team_id}:{report_id}")),
            ),
        )
        flush_internal_events_producer(_DELIVERY_TIMEOUT_SECONDS)
        delivery.get(timeout=0)
    except Exception:
        _release_ready_event_claim(team_id, report_id)
        raise


def _claim_ready_event(team_id: int, report_id: str) -> bool:
    return bool(
        SignalReport.objects.filter(
            id=report_id, team_id=team_id, status=SignalReport.Status.READY, ready_event_emitted_at__isnull=True
        ).update(ready_event_emitted_at=timezone.now())
    )


def _release_ready_event_claim(team_id: int, report_id: str) -> None:
    SignalReport.objects.filter(id=report_id, team_id=team_id).update(ready_event_emitted_at=None)


def _event_properties(team_id: int, report_id: str) -> dict:
    report = SignalReport.objects.select_related("team").get(id=report_id, team_id=team_id)
    priority = persisted_report_priority(team_id=team_id, report_id=report_id, before=timezone.now())
    return {
        "report_id": report_id,
        "title": report.title,
        "summary": report.summary,
        "priority": priority.value if priority is not None else None,
        "source_products": _source_products(report),
        "report_url": build_report_url(team_id, report_id, ReportLinkSource.WORKFLOW),
    }


def _source_products(report: SignalReport) -> list[str]:
    """The report's source products, or none when ClickHouse can't say.

    A scout report settles once, so failing the event over a context field would lose its only run.
    """
    try:
        signal_meta = fetch_source_products_for_reports(report.team, [str(report.id)]).get(str(report.id))
    except Exception:
        logger.warning(
            "inbox_report_ready_event_source_products_unavailable", team_id=report.team_id, report_id=str(report.id)
        )
        return []
    return signal_meta.source_products if signal_meta is not None else []
