"""Backfill the credentials rows of warehouse sources, and report references that point at no row.

The backfill copies the connection fields of each source from its stored `job_inputs` to its row. A source
without a reference gets one new row, and the backfill writes the reference into its `job_inputs`. A
source that already has a reference gets an update of that row, so a run can be repeated. The backfill never
merges two sources into one row, because that would put the secrets of both under one edit point.

The reconciler only reports. It lists each reference (typed-in or OAuth) that points at no row. It never
deletes a row: a row that nothing uses stays in the integrations list.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen

from products.integrations.backend.facade.api import IntegrationManager
from products.warehouse_sources.backend.facade.contracts import (
    CREDENTIALS_REFERENCE_KEY,
    SharedCredentialsError,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    WarehouseSourceCredentialsStore,
    recover_encrypted_leaves,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    connection_fields_equal,
    split_connection_fields,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

CREATED = "created"
UPDATED = "updated"
RECREATED = "recreated"
UNCHANGED = "unchanged"
SKIPPED_NO_ROW = "skipped_no_row"
SKIPPED_SHARED = "skipped_shared"
SKIPPED_DELETED = "skipped_deleted"
SKIPPED_UNREADABLE = "skipped_unreadable"
SKIPPED_UNKNOWN_TYPE = "skipped_unknown_type"
FAILED = "failed"

# The outcomes of a source whose row does not hold its stored connection fields yet.
NOT_BACKFILLED = frozenset(
    {CREATED, UPDATED, RECREATED, SKIPPED_SHARED, SKIPPED_UNREADABLE, SKIPPED_UNKNOWN_TYPE, FAILED}
)

POINTER_SUFFIX = "_integration_id"

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
class ReconcileResult:
    scanned: int
    references: int
    dangling: tuple[DanglingReference, ...]


def backfill_source_credentials(
    *,
    execute: bool,
    batch_size: int = 200,
    team_ids: Sequence[int] = (),
    source_type: str | None = None,
    limit: int | None = None,
    on_batch: Callable[[int], None] | None = None,
) -> BackfillCounts:
    """Make the row of each non-deleted source with typed-in credentials hold the connection fields of its
    stored `job_inputs`. A source with an OAuth connection, or without connection fields, gets no row.

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
    """Find each reference in the inputs of non-deleted sources that points at no row.

    A typed-in reference (`credentials_integration_id`) must point at a warehouse source row that the
    source can use. An OAuth reference (`*_integration_id`) must point at a row of the source's team.
    """
    scanned = references = 0
    dangling: list[DanglingReference] = []
    for batch in _batches(batch_size, team_ids, source_type, None):
        scanned += len(batch)
        found = _references_in_batch(batch)
        references += found.references
        dangling.extend(found.dangling)
    return ReconcileResult(scanned=scanned, references=references, dangling=tuple(dangling))


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
        .only("id", "team_id", "source_type", "job_inputs")
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
    planned: list[tuple[ExternalDataSource, dict[str, Any], Any]] = []
    for source in batch:
        source_type = str(source.source_type)
        try:
            inputs = SourceInputsStore.load_stored(source)
            fields = _stored_connection_fields(source, inputs)
        except UnreadableSourceInputsError:
            counts[(source_type, SKIPPED_UNREADABLE)] += 1
            continue
        except ValueError:
            counts[(source_type, SKIPPED_UNKNOWN_TYPE)] += 1
            continue
        if not fields or not has_typed_in_credentials(source_type):
            counts[(source_type, SKIPPED_NO_ROW)] += 1
            continue
        planned.append((source, fields, inputs.get(CREDENTIALS_REFERENCE_KEY)))
    if not planned:
        return

    stored = WarehouseSourceCredentialsStore.get_many((source, ref) for source, _, ref in planned if ref is not None)
    for source, fields, ref in planned:
        existing = stored.get(source.id)
        if ref is None:
            outcome = CREATED
        elif existing is None:
            outcome = RECREATED
        elif isinstance(existing, CredentialsUnreadable) or not connection_fields_equal(existing, fields):
            outcome = UPDATED
        else:
            counts[(str(source.source_type), UNCHANGED)] += 1
            continue
        if execute:
            try:
                outcome = _sync_source(source)
            except Exception:
                logger.exception("warehouse_source_credentials.backfill_failed", source_id=str(source.id))
                outcome = FAILED
        counts[(str(source.source_type), outcome)] += 1


def _stored_connection_fields(source: ExternalDataSource, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The connection fields of the stored `job_inputs`. A leaf that no key can decrypt raises
    `UnreadableSourceInputsError`, so its ciphertext never goes to a row."""
    fields = split_connection_fields(str(source.source_type), inputs)
    recovered = recover_encrypted_leaves(fields)
    if recovered is None:
        raise UnreadableSourceInputsError(f"job_inputs of source {source.id} hold an undecryptable value")
    return recovered


def _sync_source(source: ExternalDataSource) -> str:
    """Write the row of one source from its stored `job_inputs`, read again under the source lock.

    The lock order (source, then row) is the order of the dual write. A dual write that changed the source
    after the batch read has either committed, so this read sees its inputs and its reference, or it waits
    for this transaction. So the backfill never writes old fields, and never makes a second row.
    """
    with transaction.atomic():
        fresh = (
            ExternalDataSource.objects.select_related(None)
            .select_for_update(of=("self",))
            .only("id", "team_id", "source_type", "job_inputs", "prefix", "created_by_id", "deleted")
            .filter(pk=source.pk, team_id=source.team_id)
            .exclude(deleted=True)
            .first()
        )
        if fresh is None:
            return SKIPPED_DELETED
        inputs = SourceInputsStore.load_stored(fresh)
        fields = _stored_connection_fields(fresh, inputs)
        if not fields:
            return SKIPPED_NO_ROW
        ref = inputs.get(CREDENTIALS_REFERENCE_KEY)
        if ref is None:
            SourceInputsStore.write_credentials_reference(fresh, WarehouseSourceCredentialsStore.create(fresh, fields))
            return CREATED
        try:
            pk = WarehouseSourceCredentialsStore.update(fresh, ref, fields)
        except CredentialsNotFoundError:
            SourceInputsStore.write_credentials_reference(fresh, WarehouseSourceCredentialsStore.create(fresh, fields))
            return RECREATED
        except SharedCredentialsError:
            # Other objects use the row with other values. A person decides, so the backfill does not write.
            return SKIPPED_SHARED
        if str(pk) != str(ref):
            # A change of where a shared row connects made a new row for this source.
            SourceInputsStore.write_credentials_reference(fresh, pk)
        return UPDATED


@frozen
class _BatchReferences:
    references: int
    dangling: tuple[DanglingReference, ...]


def _references_in_batch(batch: Iterable[ExternalDataSource]) -> _BatchReferences:
    typed_in: list[tuple[ExternalDataSource, str]] = []
    oauth: dict[int, list[tuple[ExternalDataSource, str, str]]] = {}
    for source in batch:
        if source.source_type == ExternalDataSourceType.CUSTOM:
            # Custom keeps its OAuth row in another model, so its pointers are not `Integration` ids.
            continue
        try:
            inputs = SourceInputsStore.load_stored(source)
        except UnreadableSourceInputsError:
            continue
        for pointer in _pointers(inputs):
            if pointer.key == CREDENTIALS_REFERENCE_KEY:
                typed_in.append((source, pointer.value))
            else:
                oauth.setdefault(source.team_id, []).append((source, pointer.key, pointer.value))

    dangling: list[DanglingReference] = []
    found = WarehouseSourceCredentialsStore.get_many(typed_in)
    dangling.extend(
        _dangling(source, CREDENTIALS_REFERENCE_KEY, value) for source, value in typed_in if source.id not in found
    )
    for team_id, pointers in oauth.items():
        ids = {pk for _, _, value in pointers if (pk := _pk(value)) is not None}
        existing = IntegrationManager.any.get_many(team_id, ids)
        dangling.extend(_dangling(source, key, value) for source, key, value in pointers if _pk(value) not in existing)
    return _BatchReferences(
        references=len(typed_in) + sum(len(pointers) for pointers in oauth.values()), dangling=tuple(dangling)
    )


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
