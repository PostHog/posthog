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

from posthog.temporal.common.client import connect

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
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
# exceeded") and request deadlines on the visibility/history services (DEADLINE_EXCEEDED — e.g.
# "downstream duration timeout"). Riding these out in-process keeps a brief blip from failing the
# whole import activity (which would rebuild the client and restart pagination) and avoids
# error-tracking noise. Persistent failures re-raise so Temporal's activity retry still applies.
_MAX_TRANSIENT_RPC_ATTEMPTS = 6

_RETRYABLE_RPC_STATUSES = frozenset({RPCStatusCode.RESOURCE_EXHAUSTED, RPCStatusCode.DEADLINE_EXCEEDED})


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
            if attempt >= max_attempts or e.status not in _RETRYABLE_RPC_STATUSES:
                raise
            backoff = min(2 * attempt, 30)
            logger.debug(
                "TemporalIO: transient RPC error, backing off",
                status=e.status,
                backoff_seconds=backoff,
                attempt=attempt,
            )
            await asyncio.sleep(backoff)


def _async_iter_to_sync(async_iter):
    q: Queue[Any] = Queue(maxsize=5000)
    sentinel = object()

    class _Error:
        def __init__(self, exc: BaseException):
            self.exc = exc

    async def runner():
        try:
            async for item in async_iter:
                q.put(item)
        # The runner lives on a daemon thread, so an uncaught exception would
        # terminate silently and the consumer below would see only the sentinel.
        # Forward it through the queue so the caller can re-raise it.
        except BaseException as exc:
            q.put(_Error(exc))
        finally:
            q.put(sentinel)

    def run_event_loop():
        asyncio.run(runner())

    threading.Thread(target=run_event_loop, daemon=True).start()

    while True:
        item = q.get()
        if item is sentinel:
            q.task_done()
            break
        if isinstance(item, _Error):
            q.task_done()
            raise item.exc

        yield item
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


@dataclasses.dataclass
class FakeSettings:
    """Required to trick temporal.io client to think its reading from django settings"""

    TEMPORAL_SECRET_KEY: str | bytes
    TEMPORAL_FALLBACK_SECRET_KEYS: Iterable[str | bytes] = dataclasses.field(default_factory=list)
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
