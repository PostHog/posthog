import base64
import asyncio
import datetime
import threading
import dataclasses
from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum
from queue import Queue
from typing import Any, Optional, TypeVar

from structlog.types import FilteringBoundLogger
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.temporal.common.client import connect

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.temporalio import (
    TemporalIOSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class TemporalIOResource(StrEnum):
    Workflows = "workflows"
    WorkflowHistories = "workflow_histories"


ENDPOINTS = (TemporalIOResource.Workflows, TemporalIOResource.WorkflowHistories)
INCREMENTAL_ENDPOINTS = (TemporalIOResource.Workflows, TemporalIOResource.WorkflowHistories)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TemporalIOResource.Workflows: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    TemporalIOResource.WorkflowHistories: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "workflow_close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}


@dataclasses.dataclass
class TemporalIOResumeConfig:
    next_page_token: str  # Base64-encoded bytes for JSON serialization


T = TypeVar("T")

# Temporal Cloud surfaces transient server-side conditions as gRPC errors that a short backoff
# usually clears: per-namespace throttling (RESOURCE_EXHAUSTED — e.g. "namespace rate limit
# exceeded"), request deadlines on the visibility/history services (DEADLINE_EXCEEDED — e.g.
# "downstream duration timeout"), and connection-level failures (UNAVAILABLE — e.g. a DNS lookup
# blip resolving the cluster's frontend host). Riding these out in-process keeps a brief blip from
# failing the whole import activity (which would rebuild the client and restart pagination) and
# avoids error-tracking noise. Persistent failures re-raise so Temporal's activity retry still applies.
_MAX_TRANSIENT_RPC_ATTEMPTS = 6

_RETRYABLE_RPC_STATUSES = frozenset(
    {RPCStatusCode.RESOURCE_EXHAUSTED, RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE}
)

# tonic/hyper surface a mid-stream HTTP/2 transport interruption (a reset stream or a response
# body read cut short) as an RPCError with status UNKNOWN and an "h2 protocol error" message,
# rather than one of the transient statuses above. It's a connection blip, not the server
# rejecting the request, so ride it out the same way. Match the stable transport phrase, not the
# whole UNKNOWN status, so genuine server-side UNKNOWN failures still surface.
#
# tonic's timeout layer cancels a call that outruns the core client's per-request RPC deadline and
# surfaces it as status CANCELLED with the message "Timeout expired" — a client-side timeout on a
# single read (ListWorkflowExecutions / GetWorkflowExecutionHistory), not the server rejecting the
# request. It's the client-side analog of the DEADLINE_EXCEEDED case above, so ride it out too.
# Match the phrase rather than the whole CANCELLED status so a genuine cancellation still surfaces.
#
# tonic also surfaces status CANCELLED with the message "operation was canceled" when the
# underlying transport connection is closed mid-request (a known upstream pattern, e.g.
# temporalio/sdk-core#807) — another connection blip, not an intentional cancellation. Match the
# phrase, not the whole status, for the same reason as above.
_RETRYABLE_RPC_MESSAGES = ("h2 protocol error", "Timeout expired", "operation was canceled")


def _is_retryable_rpc_error(error: RPCError) -> bool:
    if error.status in _RETRYABLE_RPC_STATUSES:
        return True
    return any(phrase in error.message for phrase in _RETRYABLE_RPC_MESSAGES)


async def _with_transient_rpc_retry(
    operation: Callable[[], Awaitable[T]],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = _MAX_TRANSIENT_RPC_ATTEMPTS,
) -> T:
    attempt = 0
    while True:
        try:
            return await operation()
        except RPCError as e:
            attempt += 1
            if attempt >= max_attempts or not _is_retryable_rpc_error(e):
                raise
            backoff = min(2 * attempt, 30)
            logger.debug(
                "TemporalIO: transient RPC error, backing off",
                status=e.status,
                backoff_seconds=backoff,
                attempt=attempt,
            )
            await asyncio.sleep(backoff)


# Hand-off queue bounds between the async producer thread and the sync consumer. The item count
# keeps a stream of ordinary events flowing; the byte cap only binds once events get large, which is
# where the memory risk actually sits. Below roughly 13 KiB per event the count still governs.
_QUEUE_MAX_ITEMS = 5000
_QUEUE_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# Flat charges for values whose real footprint is not worth measuring — see `_estimate_size_bytes`.
_SCALAR_SIZE_BYTES = 16
_CONTAINER_SIZE_BYTES = 64


def _estimate_size_bytes(value: Any) -> int:
    """Rough in-memory footprint of a decoded JSON value.

    Sums string and bytes lengths, which dominate a Temporal history event because the workflow
    inputs and results embedded in it arrive base64-encoded. Scalars and container overhead are
    charged flat rates rather than measured: the figure only has to be good enough to stop a run of
    multi-megabyte events from sitting in the queue at once, and an exact walk would cost more than
    the bound saves.
    """
    if isinstance(value, str | bytes | bytearray):
        return len(value)
    if isinstance(value, dict):
        return _CONTAINER_SIZE_BYTES + sum(
            (len(key) if isinstance(key, str) else _SCALAR_SIZE_BYTES) + _estimate_size_bytes(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return _CONTAINER_SIZE_BYTES + sum(_estimate_size_bytes(item) for item in value)
    return _SCALAR_SIZE_BYTES


class _ByteBudget:
    """Admission control for the hand-off queue, bounded by the bytes its items hold.

    An item count alone does not bound memory here. Temporal embeds workflow inputs and results in
    history events, so a run of large events pins far more than a run of small ones for the same
    queue depth. Producers reserve before enqueuing and consumers release after yielding, so the
    bytes in flight stay under `max_bytes` whatever the item size.
    """

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._in_flight = 0
        self._condition = threading.Condition()

    def _admits(self, size: int) -> bool:
        # An empty budget admits anything, so a single item larger than the cap moves through on its
        # own instead of deadlocking the producer against a bound it could never satisfy.
        return self._in_flight == 0 or self._in_flight + size <= self._max_bytes

    def reserve(self, size: int) -> None:
        with self._condition:
            while not self._admits(size):
                self._condition.wait()
            self._in_flight += size

    def release(self, size: int) -> None:
        with self._condition:
            # Deliberately unclamped. Every release matches a reserve of the same size, so the total
            # returns to zero once a stream drains; clamping at zero would hide an unbalanced pair
            # (which silently widens the bound) instead of leaving it visible.
            self._in_flight -= size
            self._condition.notify_all()

    @property
    def in_flight_bytes(self) -> int:
        with self._condition:
            return self._in_flight


def _async_iter_to_sync(async_iter, max_items: int = _QUEUE_MAX_ITEMS, max_bytes: int = _QUEUE_MAX_BYTES):
    q: Queue[tuple[Any, int]] = Queue(maxsize=max_items)
    budget = _ByteBudget(max_bytes)
    sentinel = object()

    class _Error:
        def __init__(self, exc: BaseException):
            self.exc = exc

    async def runner():
        try:
            async for item in async_iter:
                size = _estimate_size_bytes(item)
                budget.reserve(size)
                q.put((item, size))
        # The runner lives on a daemon thread, so an uncaught exception would
        # terminate silently and the consumer below would see only the sentinel.
        # Forward it through the queue so the caller can re-raise it.
        except BaseException as exc:
            q.put((_Error(exc), 0))
        finally:
            q.put((sentinel, 0))

    def run_event_loop():
        asyncio.run(runner())

    threading.Thread(target=run_event_loop, daemon=True).start()

    while True:
        item, size = q.get()
        if item is sentinel:
            q.task_done()
            break
        if isinstance(item, _Error):
            q.task_done()
            raise item.exc

        try:
            yield item
        finally:
            # Release once the consumer is done with the item, not when it leaves the queue, so the
            # bound covers what the pipeline still holds rather than only what is waiting.
            budget.release(size)
            q.task_done()


def _sanitize(obj):
    """This converts some underlying non-serializable classes to their string representation"""

    def safe_convert(value):
        try:
            if isinstance(value, int | float | str | bool | dict | list | datetime.datetime):
                return value
            if value is None:
                return None
            return str(value)
        except Exception:
            return None

    return {k: safe_convert(v) for k, v in obj.items()}


@frozen
class FakeSettings:
    """Required to trick temporal.io client to think its reading from django settings"""

    TEMPORAL_SECRET_KEY: str | bytes = dataclasses.field(repr=False)
    TEMPORAL_FALLBACK_SECRET_KEYS: Iterable[str | bytes] = dataclasses.field(default_factory=list, repr=False)
    TEST: bool = False
    DEBUG: bool = False


async def _get_temporal_client(config: TemporalIOSourceConfig) -> Client:
    if config.fallback_decryption_keys:
        fallback_keys = [k.strip() for k in config.fallback_decryption_keys.split(",") if k.strip()]
    else:
        fallback_keys = []

    return await connect(
        host=config.host,
        port=config.port,
        namespace=config.namespace,
        client_cert=config.client_certificate,
        client_key=config.client_private_key,
        settings=FakeSettings(
            TEMPORAL_SECRET_KEY=config.encryption_key,
            TEMPORAL_FALLBACK_SECRET_KEYS=fallback_keys,
        )
        if config.encryption_key and len(config.encryption_key) > 0
        else None,
    )


def _encode_page_token(token: bytes) -> str:
    return base64.b64encode(token).decode("utf-8")


def _decode_page_token(token: str) -> bytes:
    return base64.b64decode(token)


async def _get_workflows(
    config: TemporalIOSourceConfig,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
):
    query: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}"'

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_page_token: bytes | None = None
    if resume_config is not None:
        next_page_token = _decode_page_token(resume_config.next_page_token)
        logger.debug("TemporalIO: resuming from next_page_token")

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query, next_page_token=next_page_token, page_size=100)

    page_count = 0
    total_count = 0
    while True:
        # Save the token that will be used to fetch this page *before* fetching.
        # On resume we re-fetch this same page — duplicates are safe thanks to primary keys.
        pre_fetch_token = workflows.next_page_token
        await _with_transient_rpc_retry(workflows.fetch_next_page, logger)
        page = workflows.current_page
        if not page:
            break

        page_count += 1
        if pre_fetch_token:
            resumable_source_manager.save_state(
                TemporalIOResumeConfig(next_page_token=_encode_page_token(pre_fetch_token))
            )
            logger.debug(f"TemporalIO: saved resume state at page {page_count} ({total_count} total workflows)")

        for item in page:
            yield _sanitize(item.__dict__)
            total_count += 1

        if not workflows.next_page_token:
            break


async def _get_workflow_histories(
    config: TemporalIOSourceConfig,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
):
    query: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}"'

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_page_token: bytes | None = None
    if resume_config is not None:
        next_page_token = _decode_page_token(resume_config.next_page_token)
        logger.debug("TemporalIO: resuming workflow histories from next_page_token")

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query, next_page_token=next_page_token, page_size=100)

    page_count = 0
    workflow_count = 0
    while True:
        # Save the token that will be used to fetch this page *before* fetching.
        # On resume we re-fetch this same page — duplicates are safe thanks to primary keys.
        pre_fetch_token = workflows.next_page_token
        await _with_transient_rpc_retry(workflows.fetch_next_page, logger)
        page = workflows.current_page
        if not page:
            break

        page_count += 1
        if pre_fetch_token:
            resumable_source_manager.save_state(
                TemporalIOResumeConfig(next_page_token=_encode_page_token(pre_fetch_token))
            )
            logger.debug(
                f"TemporalIO: saved resume state at page {page_count} ({workflow_count} total workflow histories)"
            )

        for item in page:
            try:
                handle = client.get_workflow_handle(item.id, run_id=item.run_id)
                history = await _with_transient_rpc_retry(handle.fetch_history, logger)
                history_dict = history.to_json_dict()
                events = history_dict["events"]
                for event in events:
                    id = f"{item.id}-{item.run_id}-{event['taskId']}"
                    event_with_ids = {
                        "id": id,
                        "workflow_id": item.id,
                        "run_id": item.run_id,
                        "workflow_start_time": item.start_time,
                        "workflow_close_time": item.close_time,
                        **event,
                    }
                    yield _sanitize(event_with_ids)
            except RPCError as e:
                if "workflow execution not found for" in e.message:
                    continue
                raise
            workflow_count += 1

        if not workflows.next_page_token:
            break


def temporalio_source(
    config: TemporalIOSourceConfig,
    resource: TemporalIOResource,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    if resource == TemporalIOResource.Workflows:

        async def get_workflows_iterator():
            return _get_workflows(
                config, db_incremental_field_last_value, should_use_incremental_field, resumable_source_manager, logger
            )

        workflows = _async_iter_to_sync(asyncio.run(get_workflows_iterator()))

        return SourceResponse(
            name=resource.value,
            items=lambda: workflows,
            primary_keys=["id", "run_id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["close_time"],
            sort_mode="desc",
        )
    elif resource == TemporalIOResource.WorkflowHistories:

        async def get_histories_iterator():
            return _get_workflow_histories(
                config, db_incremental_field_last_value, should_use_incremental_field, resumable_source_manager, logger
            )

        workflows = _async_iter_to_sync(asyncio.run(get_histories_iterator()))

        return SourceResponse(
            name=resource.value,
            items=lambda: workflows,
            primary_keys=["id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["workflow_close_time"],
            sort_mode="desc",
        )
    else:
        raise Exception(f"TemporalIOResource '{resource}' not recognised")
