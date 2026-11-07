"""Drains the issue change outbox into the registered subscriptions.

Delivery is at least once. Rows are marked dispatched in the transaction that claimed
them, after every matched subscription delivered them, so a crash or a transient sink
failure leaves them for the next run. A retried row goes to all its subscriptions again,
and internal events keep their uuid so downstream can recognize the repeat.
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
from products.error_tracking.backend.logic.change_subscriptions import Subscription
from products.error_tracking.backend.models import ErrorTrackingIssueChange

logger = structlog.get_logger(__name__)

DISPATCH_BATCH_SIZE = 500

SUBSCRIPTIONS: tuple[Subscription, ...] = (CDP_INTERNAL_EVENTS,)


@frozen
class DispatchOutcome:
    # Rows marked dispatched, including rows a subscription dropped.
    dispatched: int
    # Rows left in the outbox because a subscription could not deliver them. The next run retries them.
    undelivered: int


def dispatch_pending_changes(
    *, time_budget: timedelta, subscriptions: Sequence[Subscription] = SUBSCRIPTIONS
) -> DispatchOutcome:
    """Dispatch batches until the outbox is empty, a delivery fails, or the time budget runs out."""
    deadline = time.monotonic() + time_budget.total_seconds()
    dispatched = undelivered = 0
    while time.monotonic() < deadline:
        batch = _dispatch_batch(subscriptions, deadline)
        dispatched += batch.dispatched
        undelivered += batch.undelivered
        # An undelivered row stops the run, so a persistent outage retries once per run instead of in a loop.
        if batch.undelivered or batch.dispatched < DISPATCH_BATCH_SIZE:
            break
    return DispatchOutcome(dispatched=dispatched, undelivered=undelivered)


def _dispatch_batch(subscriptions: Sequence[Subscription], deadline: float) -> DispatchOutcome:
    with transaction.atomic():
        changes = list(
            ErrorTrackingIssueChange.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(dispatched_at__isnull=True)
            .order_by("created_at", "id")[:DISPATCH_BATCH_SIZE]
        )
        if not changes:
            return DispatchOutcome(dispatched=0, undelivered=0)

        changes_by_team: dict[int, list[ErrorTrackingIssueChange]] = defaultdict(list)
        for change in changes:
            changes_by_team[change.team_id].append(change)

        undelivered: set[UUID] = set()
        for team_id, team_changes in changes_by_team.items():
            # During an outage a sink waits for each team, so the budget is checked per team, not per batch.
            if time.monotonic() >= deadline:
                undelivered |= {change.id for change in team_changes}
                continue
            undelivered |= _dispatch_team(team_id, team_changes, subscriptions)

        # A row that one subscription dropped and another could not deliver still waits for the retry.
        dispatched_ids = [change.id for change in changes if change.id not in undelivered]
        # nosemgrep: idor-lookup-without-team (cross-team outbox dispatcher; ids are rows this transaction claimed)
        ErrorTrackingIssueChange.objects.unscoped().filter(id__in=dispatched_ids).update(dispatched_at=timezone.now())

    return DispatchOutcome(dispatched=len(dispatched_ids), undelivered=len(undelivered))


def _dispatch_team(
    team_id: int, changes: Sequence[ErrorTrackingIssueChange], subscriptions: Sequence[Subscription]
) -> set[UUID]:
    undelivered: set[UUID] = set()
    for subscription in subscriptions:
        try:
            matching = [change for change in changes if subscription.accepts(change)]
            if matching:
                undelivered |= subscription.sink.deliver(team_id, matching)
        except Exception:
            # No retry can fix the data that made the sink raise, and it must not head the outbox.
            logger.exception(
                "error_tracking_change_subscription_failed", team_id=team_id, subscription=subscription.key
            )
    return undelivered
