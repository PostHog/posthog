"""Dual write, shadow read and read switch of source connection fields, behind per-team flags.

With the dual-write flag on, `SourceInputsStore` copies the connection fields of each write to the
credentials row of the source, and compares the row with `job_inputs` on some reads.

With the read flag on as well, `SourceInputsStore` returns the connection fields of the row, and the other
inputs (references, selectors, sync settings, runtime state) of `job_inputs`. `job_inputs` still holds a
full copy, so a read falls back to it when the row is missing, unreadable or empty. A read never raises
because of the row or the flags. The read flag has no effect while the dual-write flag is off for the team,
because the row is then not kept up to date.

The source points at its row with `CREDENTIALS_REFERENCE_KEY` in its inputs. The first copy creates the
row and adds the reference to the inputs that the store saves. Later copies update the row. A source with
an OAuth connection has no typed-in row, so the copy does nothing for it.

The copy and the compare count and log what they find. They never change the fields that the store saves,
and they never raise, except when the API asks for a confirmation of an edit of a shared row, or when a
copy fails while the team reads from the row.
"""

import json
import time
import asyncio
import threading
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

import structlog
from prometheus_client import Counter

from products.warehouse_sources.backend.facade.contracts import (
    CREDENTIALS_REFERENCE_KEY,
    SharedCredentialsEdit,
    SharedCredentialsError,
    UnusableCredentialsReferenceError,
)
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
    same_connection_fields,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_team_flag_enabled
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
        SplitJobInputs,
    )

logger = structlog.get_logger(__name__)

DUAL_WRITE_FLAG = "warehouse-source-credentials-dual-write"
READ_FLAG = "warehouse-source-credentials-read"

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

READ_COUNTER = Counter(
    "posthog_warehouse_source_credentials_read_total",
    "Reads of warehouse source inputs with the read flag on, by the storage that gave the connection fields",
    labelnames=["result", "source_type"],
)


class _ExpiringFlags:
    def __init__(self, flag: str, ttl_seconds: float) -> None:
        self._flag = flag
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
            # A savepoint: the lookup queries `Team`, and a failed query must not abort a caller's transaction.
            with transaction.atomic():
                enabled = is_team_flag_enabled(team_id, self._flag, raise_on_error=True)
        except Exception:
            # Not cached: a failure in one context (for example a query from an event loop thread, or a
            # flag service error) must not turn the flag off for the other callers of the process.
            return False
        with self._lock:
            if len(self._entries) >= _MAX_CACHE_ENTRIES:
                self._entries.clear()
            self._entries[team_id] = (now + self._ttl_seconds, enabled)
        return enabled

    def peek(self, team_id: int) -> bool | None:
        """The cached value, or None when it is not cached. It never queries."""
        with self._lock:
            entry = self._entries.get(team_id)
        if entry is None or entry[0] <= time.monotonic():
            return None
        return entry[1]

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


_PRELOADED_ROW_ATTR = "_warehouse_source_credentials_row"

_dual_write_flags = _ExpiringFlags(DUAL_WRITE_FLAG, FLAG_CACHE_TTL_SECONDS)
_read_flags = _ExpiringFlags(READ_FLAG, FLAG_CACHE_TTL_SECONDS)
_compare_schedule = _CompareSchedule(SHADOW_COMPARE_INTERVAL_SECONDS)


def dual_write_enabled(team_id: int) -> bool:
    return _dual_write_flags.enabled(team_id)


def read_enabled(team_id: int) -> bool:
    """True when reads take the connection fields from the credentials row. Needs both flags."""
    return _read_flags.enabled(team_id) and dual_write_enabled(team_id)


def reset_caches() -> None:
    _dual_write_flags.clear()
    _read_flags.clear()
    _compare_schedule.clear()


def mirror_connection_fields(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    *,
    shared_credentials: SharedCredentialsEdit = SharedCredentialsEdit.SKIP,
) -> dict[str, Any]:
    """Copy the connection fields of ``inputs`` to the credentials row of the source, when the flag is on.

    Returns the inputs to stage: ``inputs``, with the reference to the row that now holds the fields. When
    ``inputs`` has no reference, the reference that the database holds for the source decides the row. A
    failure is counted and logged, and the caller continues with its `job_inputs` write. An edit of a row
    that other objects also use follows ``shared_credentials``.
    """
    staged = dict(inputs)
    source.__dict__.pop(_PRELOADED_ROW_ATTR, None)
    if _in_event_loop():
        # A query here raises SynchronousOnlyOperation. Async callers use `asave`, which runs in a thread.
        DUAL_WRITE_COUNTER.labels(outcome="skipped_event_loop").inc()
        logger.warning("warehouse_source_credentials.mirror_skipped_in_event_loop", **_log_context(source))
        return staged
    try:
        if not dual_write_enabled(source.team_id) or not has_typed_in_credentials(str(source.source_type)):
            return staged
        connection = _connection_fields(source.source_type, inputs)
    except Exception:
        DUAL_WRITE_COUNTER.labels(outcome="split_error").inc()
        logger.exception("warehouse_source_credentials.split_failed", **_log_context(source))
        return staged
    if not connection:
        # An OAuth connection, for example a select set to its OAuth option. The OAuth row holds the secret.
        return staged
    try:
        # A savepoint, so a failed copy leaves a caller's transaction usable. The source lock serializes the
        # copies of one source. The caller's instance can be older than the stored inputs (another writer made
        # the row after the caller read the source), so the stored reference is read under the lock.
        with transaction.atomic():
            ref = staged.get(CREDENTIALS_REFERENCE_KEY)
            stored_ref = _locked_stored_reference(source)
            outcome, pk = _write_row(source, stored_ref if ref is None else ref, connection, shared_credentials)
    except SharedCredentialsError:
        if shared_credentials == SharedCredentialsEdit.REFUSE:
            raise
        DUAL_WRITE_COUNTER.labels(outcome="shared_skip").inc()
        logger.info("warehouse_source_credentials.shared_row_skipped", **_log_context(source))
        return staged
    except Exception:
        DUAL_WRITE_COUNTER.labels(outcome="upsert_error").inc()
        logger.exception("warehouse_source_credentials.upsert_failed", **_log_context(source))
        # Reads of this team return the row, so a `job_inputs` write without the row would make reads
        # return the old connection fields. The write fails instead, before `job_inputs` changes.
        if _read_flags.enabled(source.team_id):
            raise
        return staged
    staged[CREDENTIALS_REFERENCE_KEY] = pk
    DUAL_WRITE_COUNTER.labels(outcome=outcome).inc()
    return staged


def _locked_stored_reference(source: ExternalDataSource) -> Any:
    """Lock the source row and return the reference that its stored inputs hold, or None."""
    stored = (
        ExternalDataSource._base_manager.select_for_update()
        .filter(pk=source.pk, team_id=source.team_id)
        .values_list("job_inputs", flat=True)
        .first()
    )
    if isinstance(stored, str):
        # Inputs stored as one JSON string. See `SourceInputsStore.stored_as_string`.
        try:
            stored = json.loads(stored)
        except ValueError:
            return None
    return stored.get(CREDENTIALS_REFERENCE_KEY) if isinstance(stored, Mapping) else None


def _write_row(
    source: ExternalDataSource,
    ref: Any,
    connection: Mapping[str, Any],
    shared_credentials: SharedCredentialsEdit,
) -> tuple[str, int]:
    """Create or update the row of the source. Returns the counter outcome and the pk of the row."""
    if ref is None:
        return "success", WarehouseSourceCredentialsStore.create(source, connection)
    try:
        return "success", WarehouseSourceCredentialsStore.update(
            source, ref, connection, allow_shared=shared_credentials == SharedCredentialsEdit.CONFIRMED
        )
    except CredentialsNotFoundError:
        # The reference points at no usable row. A new row keeps the copy complete.
        return "missing_row_recreated", WarehouseSourceCredentialsStore.create(source, connection)


def read_connection_fields(source: ExternalDataSource, inputs: dict[str, Any]) -> dict[str, Any]:
    """The inputs that `load` returns for the source. ``inputs`` is the decoded `job_inputs`.

    With the read flag off, the result is ``inputs`` and the shadow compare runs.
    """
    if not _reads_from_credentials(source):
        shadow_compare(source, inputs)
        return inputs
    try:
        stored: dict[str, Any] | CredentialsUnreadable | None
        if _PRELOADED_ROW_ATTR in source.__dict__:
            stored = source.__dict__[_PRELOADED_ROW_ATTR]
        elif not _needs_row(source, inputs):
            stored = None
        else:
            try:
                with transaction.atomic():  # A savepoint, as in `shadow_compare`.
                    stored = WarehouseSourceCredentialsStore.get(source, inputs.get(CREDENTIALS_REFERENCE_KEY))
            except CredentialsUnreadableError:
                stored = CredentialsUnreadable()
        result, merged = _merge(source, inputs, stored)
    except Exception:
        _count_read_error(source)
        return inputs
    _count_read(source, result)
    if result != "no_row":
        _compare_fetched(source, inputs, stored)
    return merged


def preload_connection_fields(pairs: Iterable[tuple[ExternalDataSource, Any]]) -> None:
    """Fetch the credentials rows of ``(source, reference)`` pairs in one query per team and source type,
    for later `load` calls on the same instances.

    A write through the store drops the preloaded row of that instance. A failure leaves the sources as
    they were, so `load` queries the row itself.
    """
    try:
        if _in_event_loop():
            return
        reading = [(source, ref) for source, ref in pairs if read_enabled(source.team_id)]
        if not reading:
            return
        with transaction.atomic():  # A savepoint, as in `shadow_compare`.
            stored = WarehouseSourceCredentialsStore.get_many(reading)
    except Exception:
        logger.warning("warehouse_source_credentials.preload_failed", exc_info=True)
        return
    for source, _ref in reading:
        source.__dict__[_PRELOADED_ROW_ATTR] = stored.get(source.id)


def read_connection_fields_many(
    sources: Iterable[ExternalDataSource], loaded: Mapping[UUID, dict[str, Any]]
) -> dict[UUID, dict[str, Any]]:
    """`read_connection_fields` for a list of sources, with one credentials query per team and source type."""
    reading: list[ExternalDataSource] = []
    comparing: list[ExternalDataSource] = []
    for source in sources:
        if source.id not in loaded:
            continue
        (reading if _reads_from_credentials(source) else comparing).append(source)
    shadow_compare_many(comparing, loaded)
    if not reading:
        return dict(loaded)

    result_inputs = dict(loaded)
    try:
        with transaction.atomic():  # A savepoint, as in `shadow_compare`.
            stored = WarehouseSourceCredentialsStore.get_many(
                (source, loaded[source.id].get(CREDENTIALS_REFERENCE_KEY))
                for source in reading
                if _needs_row(source, loaded[source.id])
            )
    except Exception:
        for source in reading:
            _count_read_error(source)
        return result_inputs
    for source in reading:
        inputs = loaded[source.id]
        try:
            result, result_inputs[source.id] = _merge(source, inputs, stored.get(source.id))
        except Exception:
            _count_read_error(source)
            continue
        _count_read(source, result)
        if result != "no_row":
            _compare_fetched(source, inputs, stored.get(source.id))
    return result_inputs


def shadow_compare(source: ExternalDataSource, inputs: Mapping[str, Any]) -> None:
    """Compare the connection fields of ``inputs`` with the credentials row and count the result."""
    try:
        if not _due_for_compare(source):
            return
        connection = _typed_in_connection(source, inputs)
        if connection is None:
            return
        try:
            # A savepoint: a failed query (for example a statement timeout) must not abort a transaction
            # of the caller, such as a password rotation that loads the source inside `atomic`.
            with transaction.atomic():
                stored: dict[str, Any] | CredentialsUnreadable | None = WarehouseSourceCredentialsStore.get(
                    source, inputs.get(CREDENTIALS_REFERENCE_KEY)
                )
        except CredentialsUnreadableError:
            stored = CredentialsUnreadable()
        _count_compare(source, connection, stored)
    except Exception:
        _count_compare_error(source)


def shadow_compare_many(sources: Iterable[ExternalDataSource], loaded: Mapping[UUID, Mapping[str, Any]]) -> None:
    """`shadow_compare` for a list of sources, with one credentials query per team and source type."""
    due: list[tuple[ExternalDataSource, dict[str, Any]]] = []
    try:
        for source in sources:
            if source.id not in loaded or not _due_for_compare(source):
                continue
            connection = _typed_in_connection(source, loaded[source.id])
            if connection is not None:
                due.append((source, connection))
        if not due:
            return
        with transaction.atomic():  # A savepoint, as in `shadow_compare`.
            stored = WarehouseSourceCredentialsStore.get_many(
                (source, loaded[source.id].get(CREDENTIALS_REFERENCE_KEY)) for source, _ in due
            )
    except Exception:
        for source, _ in due:
            _count_compare_error(source)
        return
    for source, connection in due:
        try:
            _count_compare(source, connection, stored.get(source.id))
        except Exception:
            _count_compare_error(source)


def _reads_from_credentials(source: ExternalDataSource) -> bool:
    try:
        if _in_event_loop():
            # The flag lookup and the row read are queries, which raise SynchronousOnlyOperation here. The read
            # keeps `job_inputs`. The counter shows such call sites for teams whose flag is in the cache.
            if _read_flags.peek(source.team_id):
                READ_COUNTER.labels(result="fallback_event_loop", source_type=str(source.source_type)).inc()
            return False
        if not _read_flags.enabled(source.team_id):
            return False
        if not dual_write_enabled(source.team_id):
            READ_COUNTER.labels(result="fallback_dual_write_off", source_type=str(source.source_type)).inc()
            return False
        return True
    except Exception:
        return False


def _needs_row(source: ExternalDataSource, inputs: Mapping[str, Any]) -> bool:
    return _typed_in_connection(source, inputs) is not None


def _merge(
    source: ExternalDataSource,
    inputs: dict[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> tuple[str, dict[str, Any]]:
    """The counter result and the inputs to return."""
    if not _needs_row(source, inputs):
        # An OAuth connection or a source without typed-in credentials: `job_inputs` holds everything.
        return "no_row", inputs
    if stored is None:
        return "fallback_missing", inputs
    if isinstance(stored, CredentialsUnreadable):
        return "fallback_unreadable", inputs
    if not stored:
        return "fallback_empty", inputs
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        SplitJobInputs,
        merge_job_inputs,
    )

    split = _split(source.source_type, inputs)
    # A key that the row holds but that is now a reference, a selector, a setting or a runtime key is
    # dropped, because `job_inputs` is the storage of those parts.
    kept_elsewhere = {*split.references, *split.selectors, *split.settings, *split.runtime}
    connection = {
        key: value for key, value in _split(source.source_type, stored).connection.items() if key not in kept_elsewhere
    }
    return "integration", merge_job_inputs(
        SplitJobInputs(
            connection=connection,
            references=split.references,
            selectors=split.selectors,
            settings=split.settings,
            runtime=split.runtime,
        )
    )


def _compare_fetched(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> None:
    # `job_inputs` is still the fallback of a read, so drift between it and the row stays visible. The row
    # is already fetched, so this compare adds no query.
    try:
        if _compare_schedule.claim(source.id):
            connection = _typed_in_connection(source, inputs)
            if connection is not None:
                _count_compare(source, connection, stored)
    except Exception:
        _count_compare_error(source)


def _count_read(source: ExternalDataSource, result: str) -> None:
    READ_COUNTER.labels(result=result, source_type=str(source.source_type)).inc()


def _count_read_error(source: ExternalDataSource) -> None:
    try:
        READ_COUNTER.labels(result="fallback_error", source_type=str(source.source_type)).inc()
        logger.warning("warehouse_source_credentials.read_failed", **_log_context(source), exc_info=True)
    except Exception:
        pass


def _typed_in_connection(source: ExternalDataSource, inputs: Mapping[str, Any]) -> dict[str, Any] | None:
    """The connection fields that the row of the source must hold, or None when the source has no typed-in row."""
    if not has_typed_in_credentials(str(source.source_type)):
        return None
    return _connection_fields(source.source_type, inputs) or None


def _due_for_compare(source: ExternalDataSource) -> bool:
    # A query in an event loop thread raises SynchronousOnlyOperation. `aload` runs `load` in a worker
    # thread, so only a direct sync call from async code skips the compare.
    if _in_event_loop():
        return False
    # A deferred field loads with one more query per source. The compare must not add queries to a read.
    if {"team_id", "source_type"} & source.get_deferred_fields():
        return False
    # The flag goes first, so only flag-on sources take a place in the schedule.
    return dual_write_enabled(source.team_id) and _compare_schedule.claim(source.id)


def _count_compare(
    source: ExternalDataSource,
    connection: Mapping[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> None:
    if stored is None:
        result = "missing_row"
    elif isinstance(stored, CredentialsUnreadable):
        result = "unreadable"
    elif not same_connection_fields(connection, stored):
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
    return _split(source_type, inputs).connection


def _split(source_type: str, inputs: Mapping[str, Any]) -> "SplitJobInputs":
    # noqa below: the classification loads the source registry. This module sits on the store import
    # path, which the model import path reaches, so the registry loads only when a flagged read or write needs it.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(ExternalDataSourceType(source_type), inputs)


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _log_context(source: ExternalDataSource) -> dict[str, Any]:
    return {"source_id": str(source.id), "team_id": source.team_id, "source_type": str(source.source_type)}


def requested_credentials_reference(
    source: ExternalDataSource, existing_inputs: Mapping[str, Any], incoming_inputs: Mapping[str, Any]
) -> Any | None:
    """The credentials reference that an API edit of the source sets, or None to keep the stored one.

    A client may point the source at another row only when the source can use that row: a warehouse
    source row of the source's team and kind, with the source's auth type. Raises
    `UnusableCredentialsReferenceError` for any other row, so a client cannot attach another team's
    credentials.
    """
    requested = incoming_inputs.get(CREDENTIALS_REFERENCE_KEY)
    if requested in (None, "") or str(requested) == str(existing_inputs.get(CREDENTIALS_REFERENCE_KEY)):
        return None
    if not WarehouseSourceCredentialsStore.usable_by(source, requested):
        raise UnusableCredentialsReferenceError(f"Source {source.id} cannot use credentials {requested!r}")
    return requested


def with_credentials_of(source: ExternalDataSource, inputs: Mapping[str, Any], ref: Any) -> dict[str, Any]:
    """``inputs`` with the connection fields of the row that ``ref`` points at, in place of their own.

    A source that an edit points at another row adopts the credentials of that row. The connection
    fields of the edit never go to the row, so the other users of the row keep their connection. Raises
    `UnusableCredentialsReferenceError` when the row does not exist or cannot be read.
    """
    try:
        fields = WarehouseSourceCredentialsStore.get(source, ref)
    except CredentialsUnreadableError as error:
        raise UnusableCredentialsReferenceError(f"Credentials {ref!r} of source {source.id} are unreadable") from error
    if fields is None:
        raise UnusableCredentialsReferenceError(f"Source {source.id} cannot use credentials {ref!r}")
    own = _connection_fields(source.source_type, inputs)
    kept = {key: value for key, value in inputs.items() if key not in own}
    return {**kept, **fields, CREDENTIALS_REFERENCE_KEY: ref}
