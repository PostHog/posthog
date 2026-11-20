from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import TYPE_CHECKING, TypeVar

import structlog
from trino.exceptions import Http502Error, Http503Error, Http504Error, HttpError, TrinoConnectionError

from posthog.sync import database_sync_to_async_pool

from products.managed_warehouse.backend.facade.contracts import TRINO_INSTANCE_REPLACED_ERROR_PREFIX

if TYPE_CHECKING:
    from collections.abc import Callable

    from trino.dbapi import Cursor

_Result = TypeVar("_Result")

TRINO_QUERY_SECONDS = 6 * 60 * 60
TRINO_QUERY_ID_LOG_SECONDS = 60
# Trino stops these queries for a cluster fault, not for the query itself, and asks the client to try
# again in a few minutes. The low-memory killer raises CLUSTER_OUT_OF_MEMORY when the whole cluster runs
# out of memory. TOO_MANY_REQUESTS_FAILED means a worker node crashed or stopped answering. A query over
# its own memory limit fails with another name. PAGE_TRANSPORT_TIMEOUT means workers lost contact while
# passing data between stages.
TRANSIENT_TRINO_ERROR_NAMES = frozenset({"CLUSTER_OUT_OF_MEMORY", "TOO_MANY_REQUESTS_FAILED", "PAGE_TRANSPORT_TIMEOUT"})
# The gateway refuses the request with an HTTP 403 before it reaches a cluster, so a retry cannot repeat any work.
# This is the start of the error text the client builds from the gateway's response body.
TRINO_POOL_NOT_ADMITTED_ERROR_PREFIX = "error 403: b'This tenant is not admitted to the pool yet"
# Trino reports ADMINISTRATIVELY_KILLED for any kill through kill_query, and an operator can kill a runaway
# query that way. Only the kill message says that the instance went away, so match the name and this text.
TRINO_INSTANCE_REPLACED_ERROR_NAME = "ADMINISTRATIVELY_KILLED"
TRINO_INSTANCE_REPLACED_MESSAGE_FRAGMENT = "the Trino instance running it was being replaced"
TRANSIENT_TRINO_ERROR_RETRY_DELAYS_SECONDS = (2 * 60, 5 * 60)
_executor = ThreadPoolExecutor(thread_name_prefix="trino-model")

logger = structlog.get_logger(__name__)


class TrinoInstanceReplacedError(RuntimeError):
    """Trino stopped every attempt of the model because it replaced the instance that ran the query."""

    def __init__(self, attempts: int, query_id: str | None) -> None:
        outcome = f"all {attempts} attempts failed" if attempts > 1 else "there was not enough time left to try again"
        message = (
            f"{TRINO_INSTANCE_REPLACED_ERROR_PREFIX}, and {outcome}. The model's query did not cause this. "
            "The model builds again on its next scheduled run, or you can run it now."
        )
        if query_id:
            message += f" Trino query ID: {query_id}"
        super().__init__(message)


class TrinoQueryControl:
    def __init__(
        self,
        query_seconds: float = TRINO_QUERY_SECONDS,
        on_processed_bytes: Callable[[int], None] | None = None,
        on_cpu_milliseconds: Callable[[int], None] | None = None,
    ) -> None:
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.cursor: Cursor | None = None
        self.deadline = monotonic() + query_seconds
        self.on_processed_bytes = on_processed_bytes
        self.on_cpu_milliseconds = on_cpu_milliseconds

    def checkpoint(self) -> None:
        if self.cancelled.is_set() or monotonic() >= self.deadline:
            raise TimeoutError("Trino model execution was canceled or exceeded its deadline")

    def attach(self, cursor: Cursor) -> None:
        self.cursor = cursor

    @property
    def query_id(self) -> str | None:
        return self.cursor.query_id if self.cursor is not None else None

    def record_processed_bytes(self, processed_bytes: object) -> None:
        if self.on_processed_bytes is not None and isinstance(processed_bytes, int):
            self.on_processed_bytes(processed_bytes)

    def record_cpu_milliseconds(self, cpu_milliseconds: object) -> None:
        if self.on_cpu_milliseconds is not None and isinstance(cpu_milliseconds, int):
            self.on_cpu_milliseconds(cpu_milliseconds)

    def _cancel_until_finished(self) -> None:
        # execute() can still be waiting for its first nextUri when cancellation arrives.
        while not self.finished.is_set():
            if self.cursor is not None:
                try:
                    self.cursor.cancel()
                except Exception:
                    pass
            self.finished.wait(0.5)

    def cancel(self) -> None:
        if not self.cancelled.is_set():
            self.cancelled.set()
            threading.Thread(target=self._cancel_until_finished, name="trino-model-cancel", daemon=True).start()


async def _log_running_query_ids(control: TrinoQueryControl) -> None:
    logged_query_id: str | None = None
    while True:
        await asyncio.sleep(TRINO_QUERY_ID_LOG_SECONDS)
        query_id = control.query_id
        if query_id is None or query_id == logged_query_id:
            continue
        logger.info("Trino model is still running", trino_query_id=query_id)
        logged_query_id = query_id


async def run_trino_model(
    execute: Callable[[TrinoQueryControl], _Result],
    *,
    query_seconds: float = TRINO_QUERY_SECONDS,
    on_processed_bytes: Callable[[int], None] | None = None,
    on_cpu_milliseconds: Callable[[int], None] | None = None,
    budget_seconds: float | None = None,
    attempt: int = 1,
) -> _Result:
    control = TrinoQueryControl(query_seconds, on_processed_bytes, on_cpu_milliseconds)
    task = asyncio.create_task(database_sync_to_async_pool(execute, executor=_executor)(control))
    query_id_logging = asyncio.create_task(_log_running_query_ids(control))
    timeout = asyncio.timeout(query_seconds)
    try:
        async with timeout:
            return await asyncio.shield(task)
    except (asyncio.CancelledError, TimeoutError) as error:
        control.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if isinstance(error, TimeoutError) and timeout.expired():
            budget = query_seconds if budget_seconds is None else budget_seconds
            attempts = f" after {attempt} attempts" if attempt > 1 else ""
            raise TimeoutError(
                f"Trino model execution exceeded its {budget / 60:g}-minute deadline{attempts}"
            ) from error
        raise
    finally:
        query_id_logging.cancel()
        control.finished.set()


def is_trino_instance_replaced_error(error: BaseException) -> bool:
    return getattr(
        error, "error_name", None
    ) == TRINO_INSTANCE_REPLACED_ERROR_NAME and TRINO_INSTANCE_REPLACED_MESSAGE_FRAGMENT in str(
        getattr(error, "message", "")
    )


def is_transient_trino_error(error: BaseException) -> bool:
    if isinstance(error, TrinoConnectionError | Http502Error | Http503Error | Http504Error):
        return True
    if getattr(error, "error_name", None) in TRANSIENT_TRINO_ERROR_NAMES:
        return True
    return is_trino_instance_replaced_error(error) or (
        isinstance(error, HttpError) and str(error).startswith(TRINO_POOL_NOT_ADMITTED_ERROR_PREFIX)
    )


async def run_trino_model_with_retries(
    execute: Callable[[TrinoQueryControl], _Result],
    *,
    query_seconds: float = TRINO_QUERY_SECONDS,
    retry_delays: tuple[float, ...] = TRANSIENT_TRINO_ERROR_RETRY_DELAYS_SECONDS,
    on_processed_bytes: Callable[[int], None] | None = None,
    on_cpu_milliseconds: Callable[[int], None] | None = None,
) -> _Result:
    """Run ``execute`` again after a transient Trino cluster fault. All attempts share one deadline.

    The usage callbacks receive each statement's final counters, in every attempt.
    """
    deadline = monotonic() + query_seconds
    for attempt, delay in enumerate((*retry_delays, None), start=1):
        try:
            return await run_trino_model(
                execute,
                query_seconds=deadline - monotonic(),
                on_processed_bytes=on_processed_bytes,
                on_cpu_milliseconds=on_cpu_milliseconds,
                budget_seconds=query_seconds,
                attempt=attempt,
            )
        except Exception as error:
            if delay is None or not is_transient_trino_error(error) or monotonic() + delay >= deadline:
                if is_trino_instance_replaced_error(error):
                    raise TrinoInstanceReplacedError(attempt, getattr(error, "query_id", None)) from error
                raise
            logger.warning(
                "Trino cluster failed the query, retrying the model",
                error_name=getattr(error, "error_name", None),
                retry_in_seconds=delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("the last attempt either returns or raises")
