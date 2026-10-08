"""Drains the issue change outbox: emit each row's internal event, then mark it dispatched.

Delivery is at least once. Rows are marked in the transaction that claimed them, after
their events are confirmed delivered, so a crash or a failed send leaves them for the
next run. A redelivered event keeps its uuid, the change id.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.cdp.internal_events import flush_internal_events_producer, produce_internal_event
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult

from products.error_tracking.backend.logic.change_events import ChangeEvent, build_change_events
from products.error_tracking.backend.models import ErrorTrackingIssueChange

logger = structlog.get_logger(__name__)

DISPATCH_BATCH_SIZE = 500
KAFKA_DELIVERY_TIMEOUT_SECONDS = 30


@frozen
class DispatchOutcome:
    dispatched: int
    emitted: int
    # Rows left in the outbox because their event was not delivered. The next run retries them.
    failed: int
    # Rows marked dispatched without an event because building it raised. Retrying cannot fix them.
    dropped: int

    def __add__(self, other: "DispatchOutcome") -> "DispatchOutcome":
        return DispatchOutcome(
            dispatched=self.dispatched + other.dispatched,
            emitted=self.emitted + other.emitted,
            failed=self.failed + other.failed,
            dropped=self.dropped + other.dropped,
        )


NOTHING_DISPATCHED = DispatchOutcome(dispatched=0, emitted=0, failed=0, dropped=0)


def dispatch_pending_changes(*, time_budget: timedelta) -> DispatchOutcome:
    """Dispatch batches until the outbox is empty, a send fails, or the time budget runs out."""
    deadline = time.monotonic() + time_budget.total_seconds()
    total = NOTHING_DISPATCHED
    while time.monotonic() < deadline:
        batch = _dispatch_batch()
        total += batch
        # A failure stops the run, so a persistent broker error retries once per run instead of in a loop.
        if batch.failed or batch.dispatched < DISPATCH_BATCH_SIZE:
            break
    return total


def _dispatch_batch() -> DispatchOutcome:
    with transaction.atomic():
        changes = list(
            ErrorTrackingIssueChange.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(dispatched_at__isnull=True)
            .order_by("created_at", "id")[:DISPATCH_BATCH_SIZE]
        )
        if not changes:
            return NOTHING_DISPATCHED

        changes_by_team: dict[int, list[ErrorTrackingIssueChange]] = defaultdict(list)
        for change in changes:
            changes_by_team[change.team_id].append(change)
        events: list[ChangeEvent] = []
        dropped = 0
        for team_id, team_changes in changes_by_team.items():
            try:
                events.extend(build_change_events(team_id, team_changes))
            except Exception:
                # A row that cannot be turned into an event would otherwise head the outbox
                # forever and block every team behind it.
                logger.exception("error_tracking_change_events_build_failed", team_id=team_id)
                dropped += len(team_changes)

        failed_change_ids = _emit(events)
        dispatched_ids = [change.id for change in changes if change.id not in failed_change_ids]
        ErrorTrackingIssueChange.objects.unscoped().filter(id__in=dispatched_ids).update(dispatched_at=timezone.now())

    return DispatchOutcome(
        dispatched=len(dispatched_ids),
        emitted=len(events) - len(failed_change_ids),
        failed=len(failed_change_ids),
        dropped=dropped,
    )


def _emit(events: Sequence[ChangeEvent]) -> set[UUID]:
    """Produce the events and wait for delivery. Returns the change ids whose event was not delivered."""
    failed: set[UUID] = set()
    pending: list[tuple[ChangeEvent, ProduceResult]] = []
    for event in events:
        try:
            pending.append(
                (event, produce_internal_event(team_id=event.team_id, event=event.event, person=event.person))
            )
        except Exception:
            # Already logged by produce_internal_event.
            failed.add(event.change_id)
    if pending:
        flush_internal_events_producer(KAFKA_DELIVERY_TIMEOUT_SECONDS)
    for event, result in pending:
        try:
            result.get(timeout=0)
        except Exception:
            logger.exception(
                "error_tracking_change_event_not_delivered", team_id=event.team_id, change_id=str(event.change_id)
            )
            failed.add(event.change_id)
    return failed
