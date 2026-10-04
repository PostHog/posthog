import time
import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from django.db import connections

from posthog.ingress.dispatch.database import bounded_statement_timeout, read_aliases

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner

# Leaves the attempt time to fail cleanly once Postgres cancels the statement.
_BUDGET_SHARE = 0.75
_MODELS = [ReplayScanner, ReplayObservation]


@contextmanager
def bounded_queries(attempt_timeout: dt.timedelta) -> Iterator[None]:
    """Cancel Postgres work in the block once it runs past most of the timeout that ends the attempt.

    A timed-out attempt leaves its thread and query running, so each retry would add another copy holding locks.
    Each statement gets what is left of the block's budget, and the block is one transaction, so keep calls to
    other services out of it.
    """
    budget_s = attempt_timeout.total_seconds() * _BUDGET_SHARE
    deadline = time.monotonic() + budget_s

    def cap_to_deadline(execute: Callable[..., Any], sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        # The driver cursor runs this outside the wrapper chain, so it does not recurse.
        context["cursor"].cursor.execute("SELECT set_config('statement_timeout', %s, true)", [f"{remaining_ms}ms"])
        return execute(sql, params, many, context)

    with ExitStack() as stack:
        stack.enter_context(bounded_statement_timeout(int(budget_s * 1000), models=_MODELS))
        for alias in read_aliases(_MODELS):
            stack.enter_context(connections[alias].execute_wrapper(cap_to_deadline))
        yield
