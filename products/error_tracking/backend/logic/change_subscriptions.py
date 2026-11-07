"""Subscriptions to issue changes: which changes they match and the sink that delivers them.

The change dispatcher matches each claimed change against every subscription and hands
each sink its team's matched changes. A sink loads the data it needs and returns the
changes it could not deliver for a transient reason; the dispatcher leaves those in the
outbox for the next run. Any exception a sink raises is treated as permanent, so a change
that cannot be processed never blocks the outbox.
"""

from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssueChange

Kind = ErrorTrackingIssueChange.Kind


class Sink(Protocol):
    def deliver(self, team_id: int, changes: Sequence[ErrorTrackingIssueChange]) -> set[UUID]:
        """Deliver one team's matched changes. Returns the change ids that were not delivered."""
        ...


@frozen
class Subscription:
    key: str
    kinds: frozenset[Kind]
    sink: Sink
    matches: Callable[[ErrorTrackingIssueChange], bool] | None = None

    def accepts(self, change: ErrorTrackingIssueChange) -> bool:
        return change.kind in self.kinds and (self.matches is None or self.matches(change))
