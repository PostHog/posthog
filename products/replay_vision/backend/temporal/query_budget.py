import time
import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from typing import Any

from django.db import DatabaseError, connections, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper

from temporalio import activity

from posthog.ingress.dispatch.database import read_aliases

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner

# Leaves the attempt time to fail cleanly once Postgres cancels the statement.
_BUDGET_SHARE = 0.75
_MODELS = [ReplayScanner, ReplayObservation]


def _aliases() -> list[str]:
    aliases = read_aliases(_MODELS)
    for model in _MODELS:
        alias = router.db_for_write(model) or "default"
        if alias not in aliases:
            aliases.append(alias)
    return aliases


def _attempt_started_at() -> float:
    if activity.in_activity():
        return activity.info().started_time.timestamp()
    return time.time()


def _set_statement_timeout(connection: BaseDatabaseWrapper, value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", [value])


@contextmanager
def _capped(connection: BaseDatabaseWrapper, deadline: float) -> Iterator[None]:
    def cap_to_deadline(execute: Callable[..., Any], sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
        remaining_ms = max(1, int((deadline - time.time()) * 1000))
        # The driver cursor runs this outside the wrapper chain, so it does not recurse.
        driver_cursor = context["cursor"].cursor
        if connection.in_atomic_block:
            driver_cursor.execute("SELECT set_config('statement_timeout', %s, true)", [f"{remaining_ms}ms"])
            return execute(sql, params, many, context)
        # SET LOCAL needs a transaction, so an autocommit statement gets one of its own.
        with transaction.atomic(using=connection.alias):
            driver_cursor.execute("SELECT set_config('statement_timeout', %s, true)", [f"{remaining_ms}ms"])
            return execute(sql, params, many, context)

    # Inside a caller's transaction the cap must not outlive the block, so the caller's value goes back.
    previous = None
    if connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('statement_timeout')")
            previous = cursor.fetchone()[0]
    try:
        with connection.execute_wrapper(cap_to_deadline):
            yield
    finally:
        if previous is not None:
            # An aborted transaction rejects the reset, and its rollback undoes the cap anyway.
            with suppress(DatabaseError):
                _set_statement_timeout(connection, previous)


@contextmanager
def bounded_queries(attempt_timeout: dt.timedelta, *, from_attempt_start: bool = True) -> Iterator[None]:
    """Cancel Postgres work in the block once it runs past most of the timeout that ends the attempt.

    A timed-out attempt leaves its thread and query running, so each retry would add another copy holding locks.
    Every block in one attempt shares the budget counted from the attempt's start; pass `from_attempt_start=False`
    to give each block its own. No connection opens until a statement runs on it.
    """
    started = _attempt_started_at() if from_attempt_start else time.time()
    deadline = started + attempt_timeout.total_seconds() * _BUDGET_SHARE
    with ExitStack() as stack:
        for alias in _aliases():
            stack.enter_context(_capped(connections[alias], deadline))
        yield
