import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager

from posthog.ingress.dispatch.database import bounded_statement_timeout

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner

# Leaves the attempt time to fail cleanly once Postgres cancels the statement.
_BUDGET_SHARE = 0.75


@contextmanager
def bounded_queries(attempt_timeout: dt.timedelta) -> Iterator[None]:
    """Cancel any Postgres statement in the block that outlives most of the timeout that ends the attempt.

    A timed-out attempt leaves its thread and query running, so each retry would add another copy holding locks.
    The block is one transaction, so keep calls to other services out of it.
    """
    with bounded_statement_timeout(
        int(attempt_timeout.total_seconds() * 1000 * _BUDGET_SHARE), models=[ReplayScanner, ReplayObservation]
    ):
        yield
