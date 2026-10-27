"""Dual write and shadow read of source connection fields, behind a per-team flag.

While `job_inputs` stays the source of truth, `SourceInputsStore` copies the connection fields of each
write to the credentials row of the source, and compares the row with `job_inputs` on some reads. Both
steps only count and log what they find: they never change what the store saves or returns, and they
never raise.
"""

import time
import asyncio
import threading
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from django.db import transaction

import structlog
from prometheus_client import Counter

from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_team_flag_enabled
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

DUAL_WRITE_FLAG = "warehouse-source-credentials-dual-write"

FLAG_CACHE_TTL_SECONDS = 60.0
# `load` runs on hot paths (the HogQL database build reads every source of a team), so each process
# compares one source at most once in this interval.
SHADOW_COMPARE_INTERVAL_SECONDS = 600.0
_MAX_CACHE_ENTRIES = 10_000

DUAL_WRITE_COUNTER = Counter(
    "posthog_warehouse_source_credentials_dual_write_total",
    "Copies of warehouse source connection fields to the credentials row, by outcome",
    labelnames=["outcome"],
)

SHADOW_COMPARE_COUNTER = Counter(
    "posthog_warehouse_source_credentials_shadow_compare_total",
    "Comparisons of warehouse source job_inputs with the credentials row, by result",
    labelnames=["result", "source_type"],
)


class _ExpiringFlags:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[int, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    def enabled(self, team_id: int) -> bool:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(team_id)
        if entry is not None and entry[0] > now:
            return entry[1]
        try:
            enabled = is_team_flag_enabled(team_id, DUAL_WRITE_FLAG, raise_on_error=True)
        except Exception:
            # Not cached: a failure in one context (for example a query from an event loop thread, or a
            # flag service error) must not turn the flag off for the other callers of the process.
            return False
        with self._lock:
            if len(self._entries) >= _MAX_CACHE_ENTRIES:
                self._entries.clear()
            self._entries[team_id] = (now + self._ttl_seconds, enabled)
        return enabled

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class _CompareSchedule:
    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = interval_seconds
        self._next_due: dict[UUID, float] = {}
        self._lock = threading.Lock()

    def claim(self, source_id: UUID) -> bool:
        """True when the source is due for a compare. The claim makes it not due for one interval."""
        now = time.monotonic()
        with self._lock:
            if self._next_due.get(source_id, 0.0) > now:
                return False
            if len(self._next_due) >= _MAX_CACHE_ENTRIES:
                self._next_due.clear()
            self._next_due[source_id] = now + self._interval_seconds
            return True

    def clear(self) -> None:
        with self._lock:
            self._next_due.clear()


_flags = _ExpiringFlags(FLAG_CACHE_TTL_SECONDS)
_compare_schedule = _CompareSchedule(SHADOW_COMPARE_INTERVAL_SECONDS)


def dual_write_enabled(team_id: int) -> bool:
    return _flags.enabled(team_id)


def reset_caches() -> None:
    _flags.clear()
    _compare_schedule.clear()


def mirror_connection_fields(source: ExternalDataSource, inputs: Mapping[str, Any]) -> None:
    """Copy the connection fields of ``inputs`` to the credentials row of the source, when the flag is on.

    A failure is counted and logged, and the caller continues with its `job_inputs` write.
    """
    if _in_event_loop():
        # A query here raises SynchronousOnlyOperation. Async callers use `asave`, which runs in a thread.
        DUAL_WRITE_COUNTER.labels(outcome="skipped_event_loop").inc()
        logger.warning("warehouse_source_credentials.mirror_skipped_in_event_loop", **_log_context(source))
        return
    try:
        if not dual_write_enabled(source.team_id):
            return
        connection = _connection_fields(source.source_type, inputs)
    except Exception:
        DUAL_WRITE_COUNTER.labels(outcome="split_error").inc()
        logger.exception("warehouse_source_credentials.split_failed", **_log_context(source))
        return
    try:
        # `update_or_create` runs in its own savepoint, so a failed copy leaves a caller's transaction usable.
        WarehouseSourceCredentialsStore.upsert(source, connection)
    except Exception:
        DUAL_WRITE_COUNTER.labels(outcome="upsert_error").inc()
        logger.exception("warehouse_source_credentials.upsert_failed", **_log_context(source))
        return
    DUAL_WRITE_COUNTER.labels(outcome="success").inc()


def shadow_compare(source: ExternalDataSource, inputs: Mapping[str, Any]) -> None:
    """Compare the connection fields of ``inputs`` with the credentials row and count the result."""
    try:
        if not _due_for_compare(source):
            return
        try:
            # A savepoint: a failed query (for example a statement timeout) must not abort a transaction
            # of the caller, such as a password rotation that loads the source inside `atomic`.
            with transaction.atomic():
                stored: dict[str, Any] | CredentialsUnreadable | None = WarehouseSourceCredentialsStore.get(source)
        except CredentialsUnreadableError:
            stored = CredentialsUnreadable()
        _count_compare(source, inputs, stored)
    except Exception:
        _count_compare_error(source)


def shadow_compare_many(sources: Iterable[ExternalDataSource], loaded: Mapping[UUID, Mapping[str, Any]]) -> None:
    """`shadow_compare` for a list of sources, with one credentials query per team."""
    due: list[ExternalDataSource] = []
    try:
        due = [source for source in sources if source.id in loaded and _due_for_compare(source)]
        if not due:
            return
        with transaction.atomic():  # A savepoint, as in `shadow_compare`.
            stored = WarehouseSourceCredentialsStore.get_many(due)
    except Exception:
        for source in due:
            _count_compare_error(source)
        return
    for source in due:
        try:
            _count_compare(source, loaded[source.id], stored.get(source.id))
        except Exception:
            _count_compare_error(source)


def _due_for_compare(source: ExternalDataSource) -> bool:
    # A query in an event loop thread raises SynchronousOnlyOperation. `aload` runs `load` in a worker
    # thread, so only a direct sync call from async code skips the compare.
    if _in_event_loop():
        return False
    # A deferred field loads with one more query per source. The compare must not add queries to a read.
    if {"team_id", "source_type"} & source.get_deferred_fields():
        return False
    return _compare_schedule.claim(source.id) and dual_write_enabled(source.team_id)


def _count_compare(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> None:
    if stored is None:
        result = "missing_row"
    elif isinstance(stored, CredentialsUnreadable):
        result = "unreadable"
    elif _comparable(_connection_fields(source.source_type, inputs)) != _comparable(stored):
        result = "field_mismatch"
    else:
        result = "match"
    SHADOW_COMPARE_COUNTER.labels(result=result, source_type=str(source.source_type)).inc()


def _count_compare_error(source: ExternalDataSource) -> None:
    try:
        SHADOW_COMPARE_COUNTER.labels(result="error", source_type=str(source.source_type)).inc()
        logger.warning("warehouse_source_credentials.shadow_compare_failed", **_log_context(source), exc_info=True)
    except Exception:
        pass


def _connection_fields(source_type: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    # noqa below: the classification loads the source registry. This module sits on the store import
    # path, which the model import path reaches, so the registry loads only when a flagged write needs it.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(ExternalDataSourceType(source_type), inputs).connection


def _comparable(value: Any) -> Any:
    # EncryptedJSONField stores each leaf as a string, so `5432` and `"5432"` are the same stored value.
    if isinstance(value, Mapping):
        return {str(key): _comparable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_comparable(item) for item in value]
    if value is None:
        return None
    return str(value)


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _log_context(source: ExternalDataSource) -> dict[str, Any]:
    return {"source_id": str(source.id), "team_id": source.team_id, "source_type": str(source.source_type)}
