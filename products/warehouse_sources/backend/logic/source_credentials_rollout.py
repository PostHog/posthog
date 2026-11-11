"""Reads and writes of source credentials in the credentials row and the reference column.

The `credentials_integration_id` column of a source holds the one integration row that the source uses:

- An OAuth source: the OAuth row that its in-use `*_integration_id` input points at. A read puts the column
  value at the path of that input.
- A source with typed-in credentials: the credentials row, which holds the connection fields. A read merges
  the row with the selectors, sync settings and runtime state of `job_inputs`.
- Any other source: nothing. A read returns `job_inputs`.

A write of a source with typed-in connection fields or an OAuth pointer strips the source: the connection
fields go only to the row, the OAuth pointer only to the column, and `job_inputs` gets the marker
`CONNECTION_FIELDS_STRIPPED_KEY`. A row write that fails raises before `job_inputs` changes.

A read never takes connection fields or an OAuth pointer from `job_inputs`. When the row is missing or
unreadable, or the column of an OAuth source is empty, the read raises `SourceCredentialsMissingError`. A
database error re-raises, so that the sync activity retries.
"""

import json
import asyncio
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

import structlog
from prometheus_client import Counter

from posthog.integrations import IntegrationReference

from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY,
    CREDENTIALS_REFERENCE_INPUT_KEY,
    STRIPPED_STORE_KEYS,
    SharedCredentialsEdit,
    SourceCredentialsMissingError,
    UnreadableSourceInputsError,
    UnusableCredentialsReferenceError,
)
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import source_key

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
        SplitJobInputs,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (
        OAuthPointer,
        PointerPath,
    )

logger = structlog.get_logger(__name__)

READ_COUNTER = Counter(
    "posthog_warehouse_source_credentials_read_total",
    "Reads of warehouse source inputs, by the storage that gave the credentials",
    labelnames=["result", "source_type"],
)

_PRELOADED_ROW_ATTR = "_warehouse_source_credentials_row"


def assign_credentials_reference(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    *,
    reference: IntegrationReference | None = None,
) -> None:
    """Set the source's `credentials_integration_id` for ``inputs`` that hold no typed-in connection fields and no
    OAuth pointer, so `strippable` is False for them. Does not save.

    Such a source uses no row (a select switched away from its typed-in option, a managed source that now gets its
    credentials elsewhere), so the column is cleared. A kept reference would leave the source a user of its old
    row, so the row could not be deleted.
    """
    source.__dict__.pop(_PRELOADED_ROW_ATTR, None)
    if reference is not None:
        source.credentials_integration_id = str(reference)
    try:
        pointer = in_use_oauth_pointer(source.source_type, inputs)
    except Exception:
        # A shape that the walk does not read: nothing can tell which row the inputs use, so the column keeps
        # its value.
        logger.warning("warehouse_source_credentials.split_failed", **_log_context(source), exc_info=True)
        return
    source.credentials_integration_id = _reference_of(pointer)


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
) -> None:
    """Create or update the row of the source, and point the source at it."""
    if source.credentials_integration_id is None:
        WarehouseSourceCredentialsStore.create(source, connection)
        return
    try:
        WarehouseSourceCredentialsStore.update(
            source, connection, allow_shared=shared_credentials == SharedCredentialsEdit.CONFIRMED
        )
    except CredentialsNotFoundError:
        # The reference points at no usable row. A new row keeps the credentials of the write.
        logger.warning("warehouse_source_credentials.missing_row_recreated", **_log_context(source))
        WarehouseSourceCredentialsStore.create(source, connection)


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

    Raises `SourceCredentialsMissingError` when the row or the column that the source needs is missing or
    unreadable, `UnreadableSourceInputsError` when the OAuth walk cannot read the inputs, and `RuntimeError`
    when such a source is read in an event loop thread. A database error re-raises. A source of an unknown
    type reads ``inputs`` as stored.
    """
    kept = _without_store_keys(inputs)
    try:
        source_class = _source_class(source.source_type)
    except ValueError:
        # No source class declares the type, so no write can have given the source a row or an OAuth pointer.
        _count_read(source, "no_row")
        return kept
    try:
        slot = _slot_of(source_class, inputs)
        reads_row = slot is None and _reads_typed_in_row(source, inputs)
    except ValueError as error:
        # The OAuth walk cannot read the shape of the inputs, so callers handle them like inputs that do not decode.
        _count_read_error(source)
        raise UnreadableSourceInputsError("job_inputs hold an OAuth field in a shape that cannot be read") from error
    except Exception:
        _count_read_error(source)
        raise
    if slot is None and not reads_row:
        _count_read(source, "no_row")
        return kept
    if _in_event_loop():
        # A query here raises SynchronousOnlyOperation, and `job_inputs` holds no copy of the credentials.
        _count_read(source, "event_loop")
        raise RuntimeError("A warehouse source with credentials must be loaded with aload from async code")
    if slot is not None:
        return _with_column_pointer(source, inputs, kept, slot)
    stored: dict[str, Any] | CredentialsUnreadable | None
    if _PRELOADED_ROW_ATTR in source.__dict__:
        stored = source.__dict__[_PRELOADED_ROW_ATTR]
    else:
        try:
            stored = WarehouseSourceCredentialsStore.get(source)
        except CredentialsUnreadableError:
            stored = CredentialsUnreadable()
        except Exception:
            _count_read_error(source)
            raise
    return _merge_row(source, kept, stored)


def preload_connection_fields(sources: Iterable[ExternalDataSource]) -> None:
    """Fetch the credentials rows of ``sources`` in one query per team and source type, for later `load`
    calls on the same instances.

    A write through the store drops the preloaded row of that instance. A failure leaves the sources as
    they were, so `load` queries the row itself.
    """
    sources = list(sources)
    try:
        if _in_event_loop() or not sources:
            return
        # A savepoint, so a failed query leaves a transaction of the caller usable for the `load` calls.
        with transaction.atomic():
            stored = WarehouseSourceCredentialsStore.get_many(sources)
    except Exception:
        logger.warning("warehouse_source_credentials.preload_failed", exc_info=True)
        return
    for source in sources:
        source.__dict__[_PRELOADED_ROW_ATTR] = stored.get(source.id)


def read_connection_fields_many(
    sources: Iterable[ExternalDataSource], loaded: Mapping[UUID, dict[str, Any]]
) -> dict[UUID, dict[str, Any]]:
    """`read_connection_fields` for a list of sources, with one credentials query per team and source type.

    A source whose row or column is missing or unreadable is left out of the result, like a source whose
    `job_inputs` does not decode. A caller that needs it calls `load`, which raises.
    """
    result: dict[UUID, dict[str, Any]] = {}
    typed_in: list[tuple[ExternalDataSource, dict[str, Any]]] = []
    for source in sources:
        if source.id not in loaded:
            continue
        inputs = loaded[source.id]
        kept = _without_store_keys(inputs)
        try:
            source_class = _source_class(source.source_type)
        except ValueError:
            _count_read(source, "no_row")
            result[source.id] = kept
            continue
        try:
            slot = _slot_of(source_class, inputs)
            reads_row = slot is None and _reads_typed_in_row(source, inputs)
        except Exception:
            _count_read_error(source)
            continue
        if slot is not None:
            try:
                result[source.id] = _with_column_pointer(source, inputs, kept, slot)
            except SourceCredentialsMissingError:
                pass
        elif reads_row:
            typed_in.append((source, kept))
        else:
            _count_read(source, "no_row")
            result[source.id] = kept
    _merge_rows_into(result, typed_in)
    return {source_id: result[source_id] for source_id in loaded if source_id in result}


def _merge_rows_into(
    result: dict[UUID, dict[str, Any]], typed_in: list[tuple[ExternalDataSource, dict[str, Any]]]
) -> None:
    if not typed_in:
        return
    try:
        # A savepoint, so a failed query leaves a transaction of the caller usable for the rest of the list.
        with transaction.atomic():
            stored = WarehouseSourceCredentialsStore.get_many(source for source, _ in typed_in)
    except Exception:
        for source, _ in typed_in:
            _count_read_error(source)
        return
    for source, kept in typed_in:
        try:
            result[source.id] = _merge_row(source, kept, stored.get(source.id))
        except SourceCredentialsMissingError:
            pass


def is_stripped(inputs: Mapping[str, Any]) -> bool:
    """True when ``inputs`` (the decoded `job_inputs`) belong to a stripped source."""
    return CONNECTION_FIELDS_STRIPPED_KEY in inputs


def stripped_at_now() -> str:
    return datetime.now(UTC).isoformat()


def strippable(source: ExternalDataSource, inputs: Mapping[str, Any]) -> bool:
    """True when ``inputs`` hold something that a strip moves out: typed-in connection fields, or an in-use
    OAuth pointer."""
    if _source_class(source.source_type).in_use_oauth_pointer(inputs) is not None:
        return True
    return _typed_in_connection(source, inputs) is not None


def stripped_job_inputs(source_type: str, inputs: Mapping[str, Any], stripped_at: str) -> dict[str, Any]:
    """The `job_inputs` of a stripped source, with the marker.

    A source with typed-in credentials keeps the selectors, sync settings and runtime state of ``inputs``. An
    OAuth source keeps all of ``inputs`` except its OAuth pointers. Both lose every OAuth pointer, also a stale
    one under an option that is not selected, because the column holds the one row that the source uses.

    Raises ValueError when the source type is unknown, because then no key can be classified as safe to keep,
    and `OAuthPointerShapeError` (a ValueError) for a shape that the OAuth walk does not read.
    """
    source_class = _source_class(source_type)
    typed_in = _slot_of(source_class, inputs) is None
    if typed_in:
        split = _split(source_type, inputs)
        kept = {**split.references, **split.selectors, **split.settings, **split.runtime}
    else:
        kept = dict(inputs)
    stripped = {
        key: value
        for key, value in _without_oauth_pointers(kept, source_class.oauth_pointer_paths).items()
        if key not in STRIPPED_STORE_KEYS
    }
    if typed_in and source_class.in_use_oauth_slot(stripped) is not None:
        # Without the connection fields the source would read as an OAuth source (Slack), so keep the mode.
        stripped[CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY] = "true"
    return {**stripped, CONNECTION_FIELDS_STRIPPED_KEY: stripped_at}


def write_stripped_credentials(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    *,
    shared_credentials: SharedCredentialsEdit = SharedCredentialsEdit.SKIP,
    reference: IntegrationReference | None = None,
) -> None:
    """Write the credentials of ``inputs`` for a stripped source: the in-use OAuth pointer to the column, or the
    connection fields to the credentials row. Sets the column on the source and does not save it.

    The row and the column are the only storage of the credentials, so a failure raises and the caller must not
    save `job_inputs`. An edit of a shared row raises `SharedCredentialsError` unless ``shared_credentials``
    confirms it, because a skipped write would lose the change.
    """
    source.__dict__.pop(_PRELOADED_ROW_ATTR, None)
    if reference is not None:
        source.credentials_integration_id = str(reference)
    try:
        source_class = _source_class(source.source_type)
        if _slot_of(source_class, inputs) is not None:
            pointer = source_class.in_use_oauth_pointer(inputs)
            if pointer is not None:
                source.credentials_integration_id = _reference_of(pointer)
            # Without a pointer in the write, the column keeps the row it names.
            return
        connection = _typed_in_connection_fields(source.source_type, inputs)
        if not connection:
            return
        current = source.credentials_integration_id
        try:
            with transaction.atomic():
                stored = _locked_typed_in_reference(source)
                source.credentials_integration_id = current if reference is not None else stored
                current = source.credentials_integration_id
                _write_row(
                    source,
                    connection,
                    SharedCredentialsEdit.CONFIRMED
                    if shared_credentials == SharedCredentialsEdit.CONFIRMED
                    else SharedCredentialsEdit.REFUSE,
                )
        except Exception:
            source.credentials_integration_id = current
            raise
    except Exception:
        logger.exception("warehouse_source_credentials.stripped_upsert_failed", **_log_context(source))
        raise


def _without_oauth_pointers(inputs: Mapping[str, Any], paths: Iterable["PointerPath"]) -> dict[str, Any]:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (  # noqa: PLC0415 — see `_source_class`
        OAuthPointerShapeError,
        with_pointer_at,
    )

    result = dict(inputs)
    for path in paths:
        try:
            result = with_pointer_at(result, path, None)
        except OAuthPointerShapeError:
            # The group on the path is not a mapping, so it holds no pointer at this path.
            continue
    return result


def _without_store_keys(inputs: Mapping[str, Any]) -> dict[str, Any]:
    # The store keys are internal to the store, so a caller never sees them.
    return {key: value for key, value in inputs.items() if key not in STRIPPED_STORE_KEYS}


def _with_column_pointer(
    source: ExternalDataSource, inputs: Mapping[str, Any], kept: dict[str, Any], slot: "PointerPath"
) -> dict[str, Any]:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (  # noqa: PLC0415 — see `_source_class`
        pointer_at,
        with_pointer_at,
    )

    column = _column_legacy_id(source)
    if column is None and not is_stripped(inputs):
        # A source not yet stripped may have never had a column written, so `job_inputs` stay the only source.
        _count_read(source, "oauth_reference" if pointer_at(kept, slot) is not None else "no_row")
        return kept
    if column is None:
        _count_read(source, "missing")
        logger.error("warehouse_source_credentials.reference_missing", **_log_context(source))
        raise SourceCredentialsMissingError()
    _count_read(source, "oauth_reference")
    return with_pointer_at(kept, slot, column)


def _merge_row(
    source: ExternalDataSource,
    kept: dict[str, Any],
    stored: dict[str, Any] | CredentialsUnreadable | None,
) -> dict[str, Any]:
    if stored is None:
        _count_read(source, "missing")
        logger.error("warehouse_source_credentials.row_missing", **_log_context(source))
        raise SourceCredentialsMissingError()
    if isinstance(stored, CredentialsUnreadable):
        _count_read(source, "unreadable")
        logger.error("warehouse_source_credentials.row_unreadable", **_log_context(source))
        raise SourceCredentialsMissingError()
    _count_read(source, "integration")
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415 — see `_split`
        SplitJobInputs,
        merge_job_inputs,
    )

    # The row is the storage of the connection fields, so connection fields that a source not yet stripped still
    # keeps in `job_inputs` are ignored. `job_inputs` is the storage of the other parts, so a row key that is now
    # a reference, a selector, a setting or a runtime key is dropped.
    split = _split(source.source_type, kept)
    kept_elsewhere = {*split.references, *split.selectors, *split.settings, *split.runtime}
    connection = {
        key: value for key, value in _split(source.source_type, stored).connection.items() if key not in kept_elsewhere
    }
    return merge_job_inputs(
        SplitJobInputs(
            connection=connection,
            references=split.references,
            selectors=split.selectors,
            settings=split.settings,
            runtime=split.runtime,
        )
    )


def _column_legacy_id(source: ExternalDataSource) -> int | None:
    stored = source.credentials_integration_id
    if stored is None:
        return None
    try:
        return IntegrationReference.parse(stored).legacy_id
    except ValueError:
        return None


def _count_read(source: ExternalDataSource, result: str) -> None:
    READ_COUNTER.labels(result=result, source_type=str(source.source_type)).inc()


def _count_read_error(source: ExternalDataSource) -> None:
    try:
        READ_COUNTER.labels(result="error", source_type=str(source.source_type)).inc()
        logger.warning("warehouse_source_credentials.read_failed", **_log_context(source), exc_info=True)
    except Exception:
        pass


def _typed_in_connection(source: ExternalDataSource, inputs: Mapping[str, Any]) -> dict[str, Any] | None:
    """The connection fields that the row of the source must hold, or None when the source has no typed-in row."""
    if _slot_of(_source_class(source.source_type), inputs) is not None:
        return None
    return _typed_in_connection_fields(source.source_type, inputs) or None


def _reads_typed_in_row(source: ExternalDataSource, inputs: Mapping[str, Any]) -> bool:
    """Whether the read takes the connection fields from the typed-in row of the source.

    A stripped source has no connection fields in `job_inputs`, so the column alone tells that it has a row. A
    source of a typed-in type with neither (a select on an option without connection fields) has no row.
    """
    if _slot_of(_source_class(source.source_type), inputs) is not None:
        return False
    if not has_typed_in_credentials(str(source.source_type)):
        return False
    return source.credentials_integration_id is not None or bool(_connection_fields(source.source_type, inputs))


def _typed_in_connection_fields(source_type: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if not has_typed_in_credentials(str(source_type)):
        return {}
    return _connection_fields(source_type, inputs)


def _connection_fields(source_type: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    return _split(source_type, inputs).connection


def _split(source_type: str, inputs: Mapping[str, Any]) -> "SplitJobInputs":
    # noqa below: the classification loads the source registry. This module sits on the store import
    # path, which the model import path reaches, so the registry loads only when a read, a write or a
    # compare needs it.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(source_key(source_type), inputs)


def _source_class(source_type: str) -> Any:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — see `_connection_fields`
        SourceRegistry,
    )

    return SourceRegistry.get_source(source_key(source_type))


def _slot_of(source_class: Any, inputs: Mapping[str, Any]) -> "PointerPath | None":
    # A stripped source with typed-in credentials can lose the field that told its authentication mode (Slack's
    # pasted token wins over its legacy OAuth pointer). The strip then keeps a key that says so.
    if CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY in inputs:
        return None
    return source_class.in_use_oauth_slot(inputs)


def split_connection_fields(source_type: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The connection fields of ``inputs``, which a credentials row holds."""
    return _connection_fields(source_type, inputs)


def in_use_oauth_slot(source_type: str, inputs: Mapping[str, Any]) -> "PointerPath | None":
    """Where ``inputs`` keep the OAuth pointer that the sync uses. See `_BaseSource.in_use_oauth_slot`.

    Raises ValueError for an unknown source type, and `OAuthPointerShapeError` (a ValueError) when the inputs
    cannot tell which OAuth field is in use.
    """
    return _slot_of(_source_class(source_type), inputs)


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
