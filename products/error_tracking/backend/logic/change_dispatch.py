"""Drains the issue change outbox into the registered subscriptions.

Delivery is at least once. Rows are marked dispatched in the transaction that claimed
them, after every matched subscription delivered them, so a crash or a transient sink
failure leaves them for the next run. A retried row goes to all its subscriptions again:
internal events keep their uuid, and workflow starts are deduplicated by workflow id.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.change_events import CDP_INTERNAL_EVENTS
from products.error_tracking.backend.logic.change_subscriptions import (
    Delivery,
    Need,
    Subscription,
    WorkflowSink,
    load_change_context,
    start_change_workflows,
)
from products.error_tracking.backend.models import ErrorTrackingIssueChange

logger = structlog.get_logger(__name__)

DISPATCH_BATCH_SIZE = 500

SUBSCRIPTIONS: tuple[Subscription, ...] = (CDP_INTERNAL_EVENTS,)


@frozen
class DispatchOutcome:
    # Rows marked dispatched, including dropped ones.
    dispatched: int
    # Successful (change, subscription) deliveries.
    delivered: int
    # Rows left in the outbox because a subscription could not deliver them. The next run retries them.
    undelivered: int
    # Rows marked dispatched although a subscription raised on them. Retrying cannot fix them.
    dropped: int

    def __add__(self, other: "DispatchOutcome") -> "DispatchOutcome":
        return DispatchOutcome(
            dispatched=self.dispatched + other.dispatched,
            delivered=self.delivered + other.delivered,
            undelivered=self.undelivered + other.undelivered,
            dropped=self.dropped + other.dropped,
        )


NOTHING_DISPATCHED = DispatchOutcome(dispatched=0, delivered=0, undelivered=0, dropped=0)


@frozen
class _TeamOutcome:
    delivered: int
    undelivered: frozenset[UUID]
    dropped: frozenset[UUID]


def dispatch_pending_changes(
    *, time_budget: timedelta, subscriptions: Sequence[Subscription] = SUBSCRIPTIONS
) -> DispatchOutcome:
    """Dispatch batches until the outbox is empty, a delivery fails, or the time budget runs out."""
    deadline = time.monotonic() + time_budget.total_seconds()
    total = NOTHING_DISPATCHED
    while time.monotonic() < deadline:
        batch = _dispatch_batch(subscriptions)
        total += batch
        # An undelivered row stops the run, so a persistent outage retries once per run instead of in a loop.
        if batch.undelivered or batch.dispatched < DISPATCH_BATCH_SIZE:
            break
    return total


def _dispatch_batch(subscriptions: Sequence[Subscription]) -> DispatchOutcome:
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

        delivered = 0
        undelivered: set[UUID] = set()
        dropped: set[UUID] = set()
        for team_id, team_changes in changes_by_team.items():
            team_outcome = _dispatch_team(team_id, team_changes, subscriptions)
            delivered += team_outcome.delivered
            undelivered |= team_outcome.undelivered
            dropped |= team_outcome.dropped

        # A row that one subscription dropped and another could not deliver still waits for the retry.
        dispatched_ids = [change.id for change in changes if change.id not in undelivered]
        ErrorTrackingIssueChange.objects.unscoped().filter(id__in=dispatched_ids).update(dispatched_at=timezone.now())

    return DispatchOutcome(
        dispatched=len(dispatched_ids),
        delivered=delivered,
        undelivered=len(undelivered),
        dropped=len(dropped - undelivered),
    )


def _dispatch_team(
    team_id: int, changes: Sequence[ErrorTrackingIssueChange], subscriptions: Sequence[Subscription]
) -> _TeamOutcome:
    try:
        matched = [
            (subscription, matching)
            for subscription in subscriptions
            if (matching := [change for change in changes if subscription.accepts(change)])
        ]
        if not matched:
            return _TeamOutcome(delivered=0, undelivered=frozenset(), dropped=frozenset())
        needs: set[Need] = set().union(*(subscription.needs for subscription, _ in matched))
        context = load_change_context(team_id, {change for _, matching in matched for change in matching}, needs)
    except Exception:
        # Matching or loading failed for the team. No retry can fix that data, and it must not head the outbox.
        logger.exception("error_tracking_change_dispatch_team_failed", team_id=team_id)
        return _TeamOutcome(delivered=0, undelivered=frozenset(), dropped=frozenset(change.id for change in changes))

    delivered = 0
    undelivered: set[UUID] = set()
    dropped: set[UUID] = set()
    for subscription, matching in matched:
        try:
            if isinstance(subscription.sink, WorkflowSink):
                failed = start_change_workflows(subscription, matching)
            else:
                failed = subscription.sink.deliver([Delivery(change=change, context=context) for change in matching])
        except Exception:
            logger.exception(
                "error_tracking_change_subscription_failed", team_id=team_id, subscription=subscription.key
            )
            dropped |= {change.id for change in matching}
            continue
        undelivered |= failed
        delivered += len(matching) - len(failed)
    return _TeamOutcome(delivered=delivered, undelivered=frozenset(undelivered), dropped=frozenset(dropped))
