"""Dual write and shadow read of source credentials references, behind a per-team flag.

While `job_inputs` stays the source of truth, `SourceInputsStore` keeps the source's
`credentials_integration_id` column in step with each write, and compares the typed-in row with
`job_inputs` on some reads. The column holds the one integration row that the source uses:

- An OAuth source: the OAuth row that its in-use `*_integration_id` input points at.
- A source with typed-in credentials: the credentials row. The first copy creates the row, and later
  copies update it.
- Any other source: nothing.

Both steps count and log what they find. They never change the inputs that the store saves or returns,
and they never raise, except when the API asks for a confirmation of an edit of a shared row.
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
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import OAuthPointer

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
            # Inside a caller's transaction, a savepoint keeps a failed `Team` query from aborting it. Outside
            # one, no transaction is opened, so the remote flag evaluation does not hold one open.
            with transaction.atomic() if transaction.get_connection().in_atomic_block else nullcontext():
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
      and logged, and the caller continues with its `job_inputs` write. An edit of a row that other
      objects also use follows ``shared_credentials``.
    - Any other source gets no reference.

    With the flag off, the column keeps its value.
    """
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


def _typed_in_connection(source: ExternalDataSource, inputs: Mapping[str, Any]) -> dict[str, Any] | None:
    """The connection fields that the row of the source must hold, or None when the source has no typed-in row."""
    if _source_class(source.source_type).in_use_oauth_slot(inputs) is not None:
        return None
    return _typed_in_connection_fields(source.source_type, inputs) or None


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
    # noqa below: the classification loads the source registry. This module sits on the store import
    # path, which the model import path reaches, so the registry loads only when a write or a compare needs it.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(ExternalDataSourceType(source_type), inputs).connection


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
