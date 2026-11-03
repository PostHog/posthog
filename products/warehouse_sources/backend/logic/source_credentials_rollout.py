"""Dual write, shadow read and read switch of source credentials, behind per-team flags.

With the dual-write flag on, `SourceInputsStore` keeps the source's `credentials_integration_id` column in
step with each write, and compares the typed-in row with `job_inputs` on some reads. The column holds the
one integration row that the source uses:

- An OAuth source: the OAuth row that its in-use `*_integration_id` input points at.
- A source with typed-in credentials: the credentials row. The first copy creates the row, and later
  copies update it.
- Any other source: nothing.

With the read flag on as well, `SourceInputsStore` returns the connection fields of the row and the OAuth
pointer of the column, with the other inputs (selectors, sync settings, runtime state) of `job_inputs`.
`job_inputs` still holds a full copy, so a read falls back to it when the row is missing, unreadable, empty
or older than `job_inputs`, and when the column does not match the OAuth pointer of `job_inputs`. A read
never raises because of the row or the flags. The read flag has no effect while the dual-write flag is off
for the team, because the row and the column are then not kept up to date.

The copy and the compare count and log what they find. They never change the inputs that the store saves,
and they never raise, except when the API asks for a confirmation of an edit of a shared row, or when a
copy fails while the team reads from the row.
"""

import json
import time
import asyncio
import threading
from collections.abc import Iterable, Mapping
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

import structlog
from prometheus_client import Counter

from posthog.integrations import IntegrationReference

from products.warehouse_sources.backend.facade.contracts import (
    CREDENTIALS_REFERENCE_INPUT_KEY,
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
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import OAuthPointer

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
            # Inside a caller's transaction, a savepoint keeps a failed `Team` query from aborting it. Outside
            # one, no transaction is opened, so the remote flag evaluation does not hold one open.
            with transaction.atomic() if transaction.get_connection().in_atomic_block else nullcontext():
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


def assign_credentials_reference(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    *,
    shared_credentials: SharedCredentialsEdit = SharedCredentialsEdit.SKIP,
    reference: IntegrationReference | None = None,
) -> None:
    """Set the source's `credentials_integration_id` for the ``inputs`` that the caller stages. Does not save.

    ``reference`` is a row that an API edit picked. It replaces the stored reference, and the row is not
    written. With the flag on:

    - An in-use OAuth pointer goes to the column. A source whose selected options hold an OAuth field gets
      no typed-in row, because the sync uses the OAuth row (Pardot keeps a typed-in `environment` next to
      its OAuth pointer).
    - Typed-in connection fields go to the credentials row, and the column points at it. When the column
      holds no typed-in row, the stored value under the source lock decides the row. A failure is counted
      and logged, and the caller continues with its `job_inputs` write, except when the team reads from the
      row: then the failure raises before `job_inputs` changes. An edit of a row that other objects also use
      follows ``shared_credentials``.
    - Any other source gets no reference.

    With the flag off, the column keeps its value.
    """
    source.__dict__.pop(_PRELOADED_ROW_ATTR, None)
    if reference is not None:
        source.credentials_integration_id = str(reference)
    if _in_event_loop():
        # A query here raises SynchronousOnlyOperation. Async callers use `asave`, which runs in a thread.
        DUAL_WRITE_COUNTER.labels(outcome="skipped_event_loop").inc()
        logger.warning("warehouse_source_credentials.mirror_skipped_in_event_loop", **_log_context(source))
        return
    if not dual_write_enabled(source.team_id):
        return
    try:
        source_class = _source_class(source.source_type)
        slot = source_class.in_use_oauth_slot(inputs)
        pointer = source_class.in_use_oauth_pointer(inputs)
        connection = _typed_in_connection_fields(source.source_type, inputs) if slot is None else {}
    except Exception:
        # An unknown source type, or a shape that the walk does not read: nothing can tell which row the
        # inputs use, so the column keeps its value.
        DUAL_WRITE_COUNTER.labels(outcome="split_error").inc()
        logger.warning("warehouse_source_credentials.split_failed", **_log_context(source), exc_info=True)
        return
    if connection:
        if reference is not None:
            # A picked row keeps its fields: `with_credentials_of` took the connection fields from it, so only
            # parser defaults can differ, and a write would turn them into an edit of the row.
            return
        _mirror_connection_fields(source, connection, shared_credentials)
        return
    # The source uses its OAuth row, or no row (a select switched away from its typed-in option, a managed
    # source that now gets its credentials elsewhere). A kept typed-in reference would leave the source a
    # user of its old row, so the row could not be deleted.
    source.credentials_integration_id = _reference_of(pointer)
    if pointer is not None:
        DUAL_WRITE_COUNTER.labels(outcome="oauth_reference").inc()


def _mirror_connection_fields(
    source: ExternalDataSource,
    connection: Mapping[str, Any],
    shared_credentials: SharedCredentialsEdit,
) -> None:
    current = source.credentials_integration_id
    try:
        # A savepoint, so a failed copy leaves a caller's transaction usable. The source lock serializes the
        # copies of one source. The caller's instance can be older than the stored column (another writer made
        # the row after the caller read the source), so the stored reference is read under the lock.
        with transaction.atomic():
            stored = _locked_typed_in_reference(source)
            current = stored
            source.credentials_integration_id = current
            outcome = _write_row(source, connection, shared_credentials)
    except SharedCredentialsError:
        source.credentials_integration_id = current
        if shared_credentials == SharedCredentialsEdit.REFUSE:
            raise
        DUAL_WRITE_COUNTER.labels(outcome="shared_skip").inc()
        logger.info("warehouse_source_credentials.shared_row_skipped", **_log_context(source))
        return
    except Exception:
        # The savepoint undid a row that the copy created, so the source must not point at it.
        source.credentials_integration_id = current
        DUAL_WRITE_COUNTER.labels(outcome="upsert_error").inc()
        logger.exception("warehouse_source_credentials.upsert_failed", **_log_context(source))
        # Reads of this team return the row, so a `job_inputs` write without the row would make reads
        # return the old connection fields. The write fails instead, before `job_inputs` changes.
        if _read_flags.enabled(source.team_id):
            raise
        return
    DUAL_WRITE_COUNTER.labels(outcome=outcome).inc()


def _locked_typed_in_reference(source: ExternalDataSource) -> str | None:
    """Lock the source row and return its stored reference, or None when the reference is not a typed-in row.

    A source that is not in the database yet (a create) has only the reference of the instance.
    """
    stored = (
        ExternalDataSource._base_manager.select_for_update()
        .filter(pk=source.pk, team_id=source.team_id)
        .values_list("credentials_integration_id", "job_inputs")
        .first()
    )
    column, stored_inputs = stored if stored is not None else (source.credentials_integration_id, None)
    if column is None:
        return None
    if isinstance(stored_inputs, str):
        # Inputs stored as one JSON string. See `SourceInputsStore.stored_as_string`.
        try:
            stored_inputs = json.loads(stored_inputs)
        except ValueError:
            stored_inputs = None
    if isinstance(stored_inputs, Mapping):
        # A source that leaves its OAuth option for typed-in fields still points at its OAuth row.
        try:
            if column == _reference_of(in_use_oauth_pointer(source.source_type, stored_inputs)):
                return None
        except Exception:
            pass
    return column


def _write_row(
    source: ExternalDataSource,
    connection: Mapping[str, Any],
    shared_credentials: SharedCredentialsEdit,
) -> str:
    """Create or update the row of the source, and point the source at it. Returns the counter outcome."""
    if source.credentials_integration_id is None:
        WarehouseSourceCredentialsStore.create(source, connection)
        return "success"
    try:
        WarehouseSourceCredentialsStore.update(
            source, connection, allow_shared=shared_credentials == SharedCredentialsEdit.CONFIRMED
        )
        return "success"
    except CredentialsNotFoundError:
        # The reference points at no usable row. A new row keeps the copy complete.
        WarehouseSourceCredentialsStore.create(source, connection)
        return "missing_row_recreated"


def in_use_oauth_pointer(source_type: str, inputs: Mapping[str, Any]) -> "OAuthPointer | None":
    """The OAuth pointer that the sync of ``inputs`` uses. See `_BaseSource.in_use_oauth_pointer`.

    Raises ValueError for an unknown source type, and `OAuthPointerShapeError` (a ValueError) when the inputs
    cannot tell which pointer is in use.
    """
    return _source_class(source_type).in_use_oauth_pointer(inputs)


def _reference_of(pointer: "OAuthPointer | None") -> str | None:
    return None if pointer is None else str(IntegrationReference.from_legacy_id(pointer.integration_id))


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
                    stored = WarehouseSourceCredentialsStore.get(source)
            except CredentialsUnreadableError:
                stored = CredentialsUnreadable()
        result, merged = _merge(source, inputs, stored)
    except Exception:
        _count_read_error(source)
        return inputs
    _count_read(source, result)
    if result in _TYPED_IN_RESULTS:
        _compare_fetched(source, inputs, stored)
    return merged


def preload_connection_fields(sources: Iterable[ExternalDataSource]) -> None:
    """Fetch the credentials rows of ``sources`` in one query per team and source type, for later `load`
    calls on the same instances.

    A write through the store drops the preloaded row of that instance. A failure leaves the sources as
    they were, so `load` queries the row itself.
    """
    try:
        if _in_event_loop():
            return
        reading = [source for source in sources if read_enabled(source.team_id)]
        if not reading:
            return
        with transaction.atomic():  # A savepoint, as in `shadow_compare`.
            stored = WarehouseSourceCredentialsStore.get_many(reading)
    except Exception:
        logger.warning("warehouse_source_credentials.preload_failed", exc_info=True)
        return
    for source in reading:
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
                source for source in reading if _needs_row(source, loaded[source.id])
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
        if result in _TYPED_IN_RESULTS:
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
                stored: dict[str, Any] | CredentialsUnreadable | None = WarehouseSourceCredentialsStore.get(source)
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
            stored = WarehouseSourceCredentialsStore.get_many(source for source, _ in due)
    except Exception:
        for source, _ in due:
            _count_compare_error(source)
        return
    for source, connection in due:
        try:
            _count_compare(source, connection, stored.get(source.id))
        except Exception:
            _count_compare_error(source)


# Results of a read of a source with typed-in credentials. The shadow compare runs after each of them.
_TYPED_IN_RESULTS = frozenset(
    {"integration", "fallback_missing", "fallback_unreadable", "fallback_empty", "fallback_mismatch"}
)


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
    try:
        return _reads_typed_in_row(source, inputs)
    except Exception:
        # A shape that the OAuth walk does not read. `_merge` counts it, and the read keeps `job_inputs`.
        return False


def _merge(
    source: ExternalDataSource,
    inputs: dict[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> tuple[str, dict[str, Any]]:
    """The counter result and the inputs to return."""
    if not _reads_typed_in_row(source, inputs):
        return _merge_oauth_reference(source, inputs)
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
    if split.connection and not same_connection_fields(split.connection, connection):
        # `job_inputs` still holds the connection fields, and a write can skip the row (the dual-write flag
        # was off, a shared row, an event loop thread). The row is then old, so the read keeps `job_inputs`.
        return "fallback_mismatch", inputs
    return "integration", merge_job_inputs(
        SplitJobInputs(
            connection=connection,
            references=split.references,
            selectors=split.selectors,
            settings=split.settings,
            runtime=split.runtime,
        )
    )


def _merge_oauth_reference(source: ExternalDataSource, inputs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The read of a source without typed-in credentials: the OAuth pointer comes from the column.

    While `job_inputs` holds the pointer too, the column is used only when it holds the same row. On a
    mismatch the read keeps `job_inputs`, because a write may have skipped the column (the dual-write flag
    was off). When `job_inputs` holds no pointer, the column alone gives it, at the path of the OAuth field
    that the selected options use.
    """
    # The walk loads the source registry, so it is off the import path of this module.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (  # noqa: PLC0415
        pointer_at,
        with_pointer_at,
    )

    slot = _source_class(source.source_type).in_use_oauth_slot(inputs)
    if slot is None:
        return "no_row", inputs
    in_inputs = pointer_at(inputs, slot)
    column = _column_legacy_id(source)
    if in_inputs is not None:
        if column == in_inputs.integration_id:
            return "oauth_reference", inputs
        return ("fallback_oauth_missing" if column is None else "fallback_oauth_mismatch"), inputs
    if column is None:
        return "no_row", inputs
    return "oauth_reference", with_pointer_at(inputs, slot, column)


def _column_legacy_id(source: ExternalDataSource) -> int | None:
    stored = source.credentials_integration_id
    if stored is None:
        return None
    try:
        return IntegrationReference.parse(stored).legacy_id
    except ValueError:
        return None


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
    if _source_class(source.source_type).in_use_oauth_slot(inputs) is not None:
        return None
    return _typed_in_connection_fields(source.source_type, inputs) or None


def _reads_typed_in_row(source: ExternalDataSource, inputs: Mapping[str, Any]) -> bool:
    """Whether the read takes the connection fields from the typed-in row of the source.

    Once `job_inputs` no longer holds the connection fields, the column alone tells that the source has a row.
    """
    if _source_class(source.source_type).in_use_oauth_slot(inputs) is not None:
        return False
    if not has_typed_in_credentials(str(source.source_type)):
        return False
    return source.credentials_integration_id is not None or bool(_connection_fields(source.source_type, inputs))


def _typed_in_connection_fields(source_type: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if not has_typed_in_credentials(str(source_type)):
        return {}
    return _connection_fields(source_type, inputs)


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
    # path, which the model import path reaches, so the registry loads only when a read, a write or a
    # compare needs it.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(ExternalDataSourceType(source_type), inputs)


def _source_class(source_type: str) -> Any:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — see `_connection_fields`
        SourceRegistry,
    )

    return SourceRegistry.get_source(ExternalDataSourceType(source_type))


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _log_context(source: ExternalDataSource) -> dict[str, Any]:
    return {"source_id": str(source.id), "team_id": source.team_id, "source_type": str(source.source_type)}


def requested_credentials_reference(
    source: ExternalDataSource, incoming_inputs: Mapping[str, Any]
) -> IntegrationReference | None:
    """The credentials row that an API edit points the source at, or None to keep the stored reference.

    A client may point the source at another row only when the source can use that row: a warehouse
    source row of the source's team and kind, with the source's auth type. Raises
    `UnusableCredentialsReferenceError` for any other row, so a client cannot attach another team's
    credentials.
    """
    requested = incoming_inputs.get(CREDENTIALS_REFERENCE_INPUT_KEY)
    if requested in (None, ""):
        return None
    reference = _parse_requested_reference(source, requested)
    if str(reference) == source.credentials_integration_id:
        return None
    try:
        fields = WarehouseSourceCredentialsStore.get_at(source, reference)
    except CredentialsUnreadableError as error:
        raise UnusableCredentialsReferenceError(
            f"Credentials {reference} of source {source.id} are unreadable"
        ) from error
    if fields is None:
        raise UnusableCredentialsReferenceError(f"Source {source.id} cannot use credentials {reference}")
    return reference


def with_credentials_of(
    source: ExternalDataSource, inputs: Mapping[str, Any], reference: IntegrationReference
) -> dict[str, Any]:
    """``inputs`` with the connection fields of the row that ``reference`` points at, in place of their own.

    A source that an edit points at another row adopts the credentials of that row. The connection
    fields of the edit never go to the row, so the other users of the row keep their connection. Raises
    `UnusableCredentialsReferenceError` when the row does not exist or cannot be read.
    """
    try:
        fields = WarehouseSourceCredentialsStore.get_at(source, reference)
    except CredentialsUnreadableError as error:
        raise UnusableCredentialsReferenceError(
            f"Credentials {reference} of source {source.id} are unreadable"
        ) from error
    if fields is None:
        raise UnusableCredentialsReferenceError(f"Source {source.id} cannot use credentials {reference}")
    own = _connection_fields(source.source_type, inputs)
    kept = {key: value for key, value in inputs.items() if key not in own and key != CREDENTIALS_REFERENCE_INPUT_KEY}
    return {**kept, **fields}


def _parse_requested_reference(source: ExternalDataSource, requested: Any) -> IntegrationReference:
    # A client can send the id as a JSON number or in the stored string form.
    try:
        if isinstance(requested, int) and not isinstance(requested, bool):
            return IntegrationReference.from_legacy_id(requested)
        return IntegrationReference.parse(str(requested))
    except ValueError as error:
        raise UnusableCredentialsReferenceError(f"Source {source.id} cannot use credentials {requested!r}") from error
