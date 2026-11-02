"""Backfill the credentials references of warehouse sources, and report references that point at no row.

The backfill fills each source's `credentials_integration_id` column with the one row the source uses:

- A source with typed-in credentials: the backfill copies the connection fields of its stored `job_inputs` to
  its row. A source without a reference gets one new row. A source with a reference gets an update of that
  row, so a run can be repeated. The backfill never merges two sources into one row, because that would put
  the secrets of both under one edit point.
- An OAuth source: the column gets the in-use `*_integration_id` pointer of its stored `job_inputs`.

Old rows can hold shapes that the OAuth walk does not read (a flat legacy key, a select stored as a string).
The backfill logs and skips them. It never guesses which pointer is in use.

The reconciler only reports. It lists each reference that points at no row, and each OAuth source whose
column differs from its in-use pointer. It never deletes a row: a row that nothing uses stays in the
integrations list.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationReference

from products.warehouse_sources.backend.facade.contracts import SharedCredentialsError, UnreadableSourceInputsError
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    WarehouseSourceCredentialsStore,
    recover_encrypted_leaves,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    connection_fields_equal,
    in_use_oauth_slot,
    split_connection_fields,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (
    OAuthPointerShapeError,
    PointerPath,
    pointer_at,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

CREATED = "created"
UPDATED = "updated"
RECREATED = "recreated"
UNCHANGED = "unchanged"
OAUTH_LINKED = "oauth_linked"
SKIPPED_SHAPE = "skipped_unreadable_shape"
SKIPPED_NO_ROW = "skipped_no_row"
SKIPPED_SHARED = "skipped_shared"
SKIPPED_DELETED = "skipped_deleted"
SKIPPED_UNREADABLE = "skipped_unreadable"
SKIPPED_UNKNOWN_TYPE = "skipped_unknown_type"
FAILED = "failed"

# The outcomes of a source whose row does not hold its stored connection fields yet.
NOT_BACKFILLED = frozenset(
    {
        CREATED,
        UPDATED,
        RECREATED,
        OAUTH_LINKED,
        SKIPPED_SHARED,
        SKIPPED_UNREADABLE,
        SKIPPED_SHAPE,
        SKIPPED_UNKNOWN_TYPE,
        FAILED,
    }
)

POINTER_SUFFIX = "_integration_id"
# The key under which reports name the reference column.
COLUMN_KEY = "credentials_integration_id"

# Counts keyed by (source_type, outcome).
BackfillCounts = Counter[tuple[str, str]]


@frozen
class DanglingReference:
    """A reference in a source's inputs that points at no row the source can use."""

    team_id: int
    source_id: str
    source_type: str
    key: str
    integration_id: str


@frozen
class ReferenceMismatch:
    """An OAuth source whose reference column differs from the in-use pointer of its inputs."""

    team_id: int
    source_id: str
    source_type: str
    path: str
    column: str | None
    pointer: str


@frozen
class ReconcileResult:
    scanned: int
    references: int
    dangling: tuple[DanglingReference, ...]
    mismatched: tuple[ReferenceMismatch, ...] = ()


def backfill_source_credentials(
    *,
    execute: bool,
    batch_size: int = 200,
    team_ids: Sequence[int] = (),
    source_type: str | None = None,
    limit: int | None = None,
    on_batch: Callable[[int], None] | None = None,
) -> BackfillCounts:
    """Make the reference column of each non-deleted source point at the row it uses. A source with typed-in
    credentials gets a row that holds the connection fields of its stored `job_inputs`. An OAuth source gets
    the in-use OAuth pointer of its stored `job_inputs` in its column.

    With ``execute`` false the function only counts what it would do. Sources are read in id order, so a
    run can be repeated and a crash loses nothing.
    """
    counts: BackfillCounts = Counter()
    for batch in _batches(batch_size, team_ids, source_type, limit):
        _process_batch(batch, execute, counts)
        if on_batch:
            on_batch(len(batch))
    return counts


def reconcile_credential_references(
    *, batch_size: int = 500, team_ids: Sequence[int] = (), source_type: str | None = None
) -> ReconcileResult:
    """Find each reference of non-deleted sources that points at no row, and each OAuth source whose column
    differs from the in-use pointer of its inputs.

    The column of a source with typed-in credentials must point at a warehouse source row that the source can
    use. The column of an OAuth source, and each OAuth reference (`*_integration_id`) in the inputs, must point
    at a row of the source's team.
    """
    scanned = references = 0
    dangling: list[DanglingReference] = []
    mismatched: list[ReferenceMismatch] = []
    for batch in _batches(batch_size, team_ids, source_type, None):
        scanned += len(batch)
        found = _references_in_batch(batch)
        references += found.references
        dangling.extend(found.dangling)
        mismatched.extend(found.mismatched)
    return ReconcileResult(
        scanned=scanned, references=references, dangling=tuple(dangling), mismatched=tuple(mismatched)
    )


def _batches(
    batch_size: int, team_ids: Sequence[int], source_type: str | None, limit: int | None
) -> Iterable[list[ExternalDataSource]]:
    last_id: UUID | None = None
    remaining = limit
    while remaining is None or remaining > 0:
        page_size = batch_size if remaining is None else min(batch_size, remaining)
        batch = _next_sources(last_id, page_size, team_ids, source_type)
        if not batch:
            return
        last_id = batch[-1].id
        yield batch
        if remaining is not None:
            remaining -= len(batch)


def _next_sources(
    after_id: UUID | None, size: int, team_ids: Sequence[int], source_type: str | None
) -> list[ExternalDataSource]:
    # `select_related(None)` clears the default manager's join, which `only()` cannot defer past.
    queryset = (
        ExternalDataSource.objects.exclude(deleted=True)
        .select_related(None)
        .only("id", "team_id", "source_type", "job_inputs", "credentials_integration_id")
        .order_by("id")
    )
    if after_id is not None:
        queryset = queryset.filter(id__gt=after_id)
    if team_ids:
        queryset = queryset.filter(team_id__in=list(team_ids))
    if source_type:
        queryset = queryset.filter(source_type=source_type)
    return list(queryset[:size])


def _process_batch(batch: Iterable[ExternalDataSource], execute: bool, counts: BackfillCounts) -> None:
    planned: list[tuple[ExternalDataSource, dict[str, Any]]] = []
    for source in batch:
        source_type = str(source.source_type)
        try:
            plan = _plan(source)
        except UnreadableSourceInputsError:
            counts[(source_type, SKIPPED_UNREADABLE)] += 1
            continue
        except OAuthPointerShapeError:
            _log_shape(source)
            counts[(source_type, SKIPPED_SHAPE)] += 1
            continue
        except ValueError:
            counts[(source_type, SKIPPED_UNKNOWN_TYPE)] += 1
            continue
        if plan == OAUTH_LINKED:
            _run(source, execute, plan, counts)
            continue
        if isinstance(plan, str):
            counts[(source_type, plan)] += 1
            continue
        planned.append((source, plan))
    if not planned:
        return

    stored = WarehouseSourceCredentialsStore.get_many(source for source, _ in planned)
    for source, fields in planned:
        existing = stored.get(source.id)
        if source.credentials_integration_id is None:
            outcome = CREATED
        elif existing is None:
            outcome = RECREATED
        elif isinstance(existing, CredentialsUnreadable) or not connection_fields_equal(existing, fields):
            outcome = UPDATED
        else:
            counts[(str(source.source_type), UNCHANGED)] += 1
            continue
        _run(source, execute, outcome, counts)


def _plan(source: ExternalDataSource) -> dict[str, Any] | str:
    """The connection fields that the row of a source with typed-in credentials must hold, or the outcome of
    a source that needs no row write (an OAuth source, a source without connection fields)."""
    inputs = SourceInputsStore.load_stored(source)
    slot = in_use_oauth_slot(str(source.source_type), inputs)
    if slot is not None:
        return _oauth_outcome(source, inputs, slot)
    fields = _stored_connection_fields(source, inputs)
    if not fields or not has_typed_in_credentials(str(source.source_type)):
        return SKIPPED_NO_ROW
    return fields


def _oauth_outcome(source: ExternalDataSource, inputs: Mapping[str, Any], slot: PointerPath) -> str:
    pointer = pointer_at(inputs, slot)
    if pointer is None:
        # The inputs hold no pointer, so they cannot tell the row. A column that a later step filled stays.
        return SKIPPED_NO_ROW
    if source.credentials_integration_id == str(IntegrationReference.from_legacy_id(pointer.integration_id)):
        return UNCHANGED
    return OAUTH_LINKED


def _run(source: ExternalDataSource, execute: bool, outcome: str, counts: BackfillCounts) -> None:
    if execute:
        try:
            outcome = _sync_source(source)
        except OAuthPointerShapeError:
            _log_shape(source)
            outcome = SKIPPED_SHAPE
        except Exception:
            logger.exception("warehouse_source_credentials.backfill_failed", source_id=str(source.id))
            outcome = FAILED
    counts[(str(source.source_type), outcome)] += 1


def _log_shape(source: ExternalDataSource) -> None:
    logger.warning(
        "warehouse_source_credentials.backfill_skipped_unreadable_shape",
        source_id=str(source.id),
        team_id=source.team_id,
        source_type=str(source.source_type),
    )


def _stored_connection_fields(source: ExternalDataSource, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The connection fields of the stored `job_inputs`. A leaf that no key can decrypt raises
    `UnreadableSourceInputsError`, so its ciphertext never goes to a row."""
    fields = split_connection_fields(str(source.source_type), inputs)
    recovered = recover_encrypted_leaves(fields)
    if recovered is None:
        raise UnreadableSourceInputsError(f"job_inputs of source {source.id} hold an undecryptable value")
    return recovered


def _sync_source(source: ExternalDataSource) -> str:
    """Write the reference (and for typed-in credentials the row) of one source from its stored `job_inputs`,
    read again under the source lock.

    The lock order (source, then row) is the order of the dual write. A dual write that changed the source
    after the batch read has either committed, so this read sees its inputs and its column, or it waits for
    this transaction. So the backfill never writes old fields, and never makes a second row.
    """
    with transaction.atomic():
        fresh = (
            ExternalDataSource.objects.select_related(None)
            .select_for_update(of=("self",))
            .only(
                "id",
                "team_id",
                "source_type",
                "job_inputs",
                "credentials_integration_id",
                "prefix",
                "created_by_id",
                "deleted",
            )
            .filter(pk=source.pk, team_id=source.team_id)
            .exclude(deleted=True)
            .first()
        )
        if fresh is None:
            return SKIPPED_DELETED
        inputs = SourceInputsStore.load_stored(fresh)
        slot = in_use_oauth_slot(str(fresh.source_type), inputs)
        if slot is not None:
            outcome = _oauth_outcome(fresh, inputs, slot)
            pointer = pointer_at(inputs, slot)
            if outcome == OAUTH_LINKED and pointer is not None:
                SourceInputsStore.write_credentials_reference(
                    fresh, IntegrationReference.from_legacy_id(pointer.integration_id)
                )
            return outcome
        fields = _stored_connection_fields(fresh, inputs)
        if not fields or not has_typed_in_credentials(str(fresh.source_type)):
            return SKIPPED_NO_ROW
        before = fresh.credentials_integration_id
        if before is None:
            SourceInputsStore.write_credentials_reference(fresh, WarehouseSourceCredentialsStore.create(fresh, fields))
            return CREATED
        try:
            reference = WarehouseSourceCredentialsStore.update(fresh, fields)
        except CredentialsNotFoundError:
            SourceInputsStore.write_credentials_reference(fresh, WarehouseSourceCredentialsStore.create(fresh, fields))
            return RECREATED
        except SharedCredentialsError:
            # Other objects use the row with other values. A person decides, so the backfill does not write.
            return SKIPPED_SHARED
        if str(reference) != before:
            # A change of where a shared row connects made a new row for this source.
            SourceInputsStore.write_credentials_reference(fresh, reference)
        return UPDATED


@frozen
class _BatchReferences:
    references: int
    dangling: tuple[DanglingReference, ...]
    mismatched: tuple[ReferenceMismatch, ...]


def _references_in_batch(batch: Iterable[ExternalDataSource]) -> _BatchReferences:
    typed_in: list[ExternalDataSource] = []
    # (source, key, value) of each pointer that must name an OAuth row of the source's team, by team.
    oauth: dict[int, list[tuple[ExternalDataSource, str, str]]] = {}
    # Columns of sources whose inputs cannot tell the kind of row. Any row of the team satisfies them.
    unknown: dict[int, list[tuple[ExternalDataSource, str, str]]] = {}
    unresolvable: list[tuple[ExternalDataSource, str]] = []
    mismatched: list[ReferenceMismatch] = []
    for source in batch:
        if not _pointers_are_integration_ids(str(source.source_type)):
            continue
        try:
            inputs: Mapping[str, Any] | None = SourceInputsStore.load_stored(source)
        except UnreadableSourceInputsError:
            inputs = None
        readable, slot = _read_slot(source, inputs)
        column = source.credentials_integration_id
        if column is not None:
            if _column_pk(column) is None:
                unresolvable.append((source, column))
            elif not readable:
                unknown.setdefault(source.team_id, []).append((source, COLUMN_KEY, column))
            elif slot is None:
                typed_in.append(source)
            else:
                oauth.setdefault(source.team_id, []).append((source, COLUMN_KEY, column))
        if inputs is None:
            continue
        for pointer in _pointers(inputs):
            oauth.setdefault(source.team_id, []).append((source, pointer.key, pointer.value))
        in_use = pointer_at(inputs, slot) if slot is not None else None
        if in_use is not None and column != str(IntegrationReference.from_legacy_id(in_use.integration_id)):
            mismatched.append(
                ReferenceMismatch(
                    team_id=source.team_id,
                    source_id=str(source.id),
                    source_type=str(source.source_type),
                    path=".".join(in_use.path),
                    column=column,
                    pointer=str(in_use.integration_id),
                )
            )

    dangling: list[DanglingReference] = [_dangling(source, COLUMN_KEY, value) for source, value in unresolvable]
    found = WarehouseSourceCredentialsStore.get_many(typed_in)
    dangling.extend(
        _dangling(source, COLUMN_KEY, str(source.credentials_integration_id))
        for source in typed_in
        if source.id not in found
    )
    for rows, by_team in ((IntegrationManager.any, oauth), (IntegrationManager.any.with_source_rows(), unknown)):
        for team_id, pointers in by_team.items():
            ids = {pk for _, key, value in pointers if (pk := _pointer_pk(key, value)) is not None}
            existing = rows.get_many(team_id, ids)
            dangling.extend(
                _dangling(source, key, value)
                for source, key, value in pointers
                if _pointer_pk(key, value) not in existing
            )
    return _BatchReferences(
        references=len(unresolvable)
        + len(typed_in)
        + sum(len(pointers) for by_team in (oauth, unknown) for pointers in by_team.values()),
        dangling=tuple(dangling),
        mismatched=tuple(mismatched),
    )


def _read_slot(source: ExternalDataSource, inputs: Mapping[str, Any] | None) -> tuple[bool, PointerPath | None]:
    """Whether the inputs tell the kind of row the source uses, and the in-use OAuth field."""
    if inputs is None:
        return False, None
    try:
        return True, in_use_oauth_slot(str(source.source_type), inputs)
    except ValueError:
        # An unknown source type, or an old shape that the walk does not read.
        return False, None


def _column_pk(column: str) -> int | None:
    try:
        return IntegrationReference.parse(column).legacy_id
    except ValueError:
        return None


def _pointer_pk(key: str, value: str) -> int | None:
    return _column_pk(value) if key == COLUMN_KEY else _pk(value)


def _pointers_are_integration_ids(source_type: str) -> bool:
    # The registry loads every source, so keep it off this module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — heavy import
        SourceRegistry,
    )

    try:
        return SourceRegistry.get_source(
            ExternalDataSourceType(source_type)
        ).integration_id_fields_point_at_integrations
    except ValueError:
        return True


@frozen
class _Pointer:
    key: str
    value: str


def _pointers(inputs: Mapping[str, Any]) -> list[_Pointer]:
    # Switch groups and select options nest their fields one level down.
    pointers: list[_Pointer] = []
    for key, value in inputs.items():
        if isinstance(value, Mapping):
            pointers.extend(_pointers(value))
        elif key.endswith(POINTER_SUFFIX) and value not in (None, ""):
            pointers.append(_Pointer(key=key, value=str(value)))
    return pointers


def _pk(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _dangling(source: ExternalDataSource, key: str, value: str) -> DanglingReference:
    return DanglingReference(
        team_id=source.team_id,
        source_id=str(source.id),
        source_type=str(source.source_type),
        key=key,
        integration_id=value,
    )
