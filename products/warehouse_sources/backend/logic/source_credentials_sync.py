"""Backfill and reconcile the credentials rows of warehouse sources.

The backfill copies the connection fields of each source from its stored `job_inputs` to its row. The
reconciler deletes rows that no live source owns. Both work in batches, and neither depends on a feature flag.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.contracts import UnreadableSourceInputsError
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialRowRef,
    CredentialsUnreadable,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    connection_fields_equal,
    is_stripped,
    split_connection_fields,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)

CREATED = "created"
UPDATED = "updated"
UNCHANGED = "unchanged"
SKIPPED_UNREADABLE = "skipped_unreadable"
SKIPPED_UNKNOWN_TYPE = "skipped_unknown_type"
# The source is stripped: `job_inputs` has no connection fields to copy, and the row is the only copy.
SKIPPED_STRIPPED = "skipped_stripped"
STRIPPED_ROW_MISSING = "stripped_row_missing_or_unreadable"
FAILED = "failed"

# `SourceInputsStore.create` writes the credentials row before it inserts the source. A row younger than
# this may belong to a source that is being created, so the reconciler never treats it as an orphan.
ORPHAN_GRACE_PERIOD = timedelta(hours=1)

# Counts keyed by (source_type, outcome).
BackfillCounts = Counter[tuple[str, str]]


@frozen
class ReconcileResult:
    scanned: int
    orphans: int
    deleted: int


def backfill_source_credentials(
    *,
    execute: bool,
    batch_size: int = 200,
    team_ids: Sequence[int] = (),
    source_type: str | None = None,
    limit: int | None = None,
    on_batch: Callable[[int], None] | None = None,
) -> BackfillCounts:
    """Create or update the row of each non-deleted source so that it holds the connection fields of the
    stored `job_inputs`. A source with no connection fields gets a row with empty fields: the read path
    treats an empty row for such a source as a normal read, while a missing row is a fallback.

    With ``execute`` false the function only counts what it would do. Sources are read in id order, so a
    run can be repeated and a crash loses nothing.
    """
    counts: BackfillCounts = Counter()
    last_id: UUID | None = None
    remaining = limit
    while remaining is None or remaining > 0:
        page_size = batch_size if remaining is None else min(batch_size, remaining)
        batch = next_source_batch(last_id, page_size, team_ids, source_type)
        if not batch:
            break
        last_id = batch[-1].id
        _process_batch(batch, execute, counts)
        if on_batch:
            on_batch(len(batch))
        if remaining is not None:
            remaining -= len(batch)
    return counts


def reconcile_orphan_credentials(*, execute: bool, batch_size: int = 500) -> ReconcileResult:
    """Find rows whose source id is not a non-deleted source of the same team. Delete them when ``execute``.

    Rows younger than `ORPHAN_GRACE_PERIOD` are not scanned, so a source in creation keeps its row.
    """
    scanned = orphans = deleted = 0
    cursor = 0
    created_before = timezone.now() - ORPHAN_GRACE_PERIOD
    while True:
        page = WarehouseSourceCredentialsStore.list_row_refs(
            after_pk=cursor, limit=batch_size, created_before=created_before
        )
        if not page:
            break
        cursor = page[-1][0]
        refs = [ref for _, ref in page]
        orphan_refs = _orphans_of(refs)
        scanned += len(refs)
        orphans += len(orphan_refs)
        if execute:
            by_team: dict[int, list[str]] = {}
            for ref in orphan_refs:
                by_team.setdefault(ref.team_id, []).append(ref.source_id)
            for team_id, source_ids in by_team.items():
                deleted += WarehouseSourceCredentialsStore.delete_for_source_ids(team_id, source_ids)
    return ReconcileResult(scanned=scanned, orphans=orphans, deleted=deleted)


def next_source_batch(
    after_id: UUID | None, size: int, team_ids: Sequence[int], source_type: str | None
) -> list[ExternalDataSource]:
    """One page of non-deleted sources in id order, with only the fields that the credentials tools read."""
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
    wanted: dict[UUID, tuple[ExternalDataSource, dict[str, object]]] = {}
    stripped: list[ExternalDataSource] = []
    for source in batch:
        source_type = str(source.source_type)
        try:
            stored_inputs = SourceInputsStore.load_stored(source)
            if is_stripped(stored_inputs):
                stripped.append(source)
                continue
            fields = split_connection_fields(source_type, stored_inputs)
        except UnreadableSourceInputsError:
            counts[(source_type, SKIPPED_UNREADABLE)] += 1
            continue
        except ValueError:
            counts[(source_type, SKIPPED_UNKNOWN_TYPE)] += 1
            continue
        wanted[source.id] = (source, fields)
    _check_stripped(stripped, counts)
    if not wanted:
        return

    stored = WarehouseSourceCredentialsStore.get_many([source for source, _ in wanted.values()])
    for source_id, (source, fields) in wanted.items():
        source_type = str(source.source_type)
        existing = stored.get(source_id)
        if existing is None:
            outcome = CREATED
        elif isinstance(existing, CredentialsUnreadable) or not connection_fields_equal(existing, fields):
            outcome = UPDATED
        else:
            counts[(source_type, UNCHANGED)] += 1
            continue
        if execute:
            try:
                if not _write_row(source, fields):
                    outcome = SKIPPED_STRIPPED
            except Exception:
                logger.exception("warehouse_source_credentials.backfill_failed", source_id=str(source_id))
                outcome = FAILED
        counts[(source_type, outcome)] += 1


class _SourceStrippedMeanwhile(Exception):
    pass


def _write_row(source: ExternalDataSource, fields: dict[str, object]) -> bool:
    """Upsert the row from the batch snapshot, then re-read the stored `job_inputs` while the row is locked.

    A dual write (`SourceInputsStore.save`) changes the row and the source in one transaction. Once the
    upsert holds the row lock, such a write has either committed both, so the re-read sees its inputs, or
    it waits for this transaction and overwrites the row after it. A rotation between the batch read and
    this write is therefore never undone by the snapshot.

    The re-read locks the source, like the strip does, so it sees a strip that ran after the batch read.
    The row of a stripped source is the only copy of its credentials, so the upsert is rolled back and the
    result is False.
    """
    try:
        with transaction.atomic():
            WarehouseSourceCredentialsStore.upsert(source, fields)
            fresh = (
                ExternalDataSource.objects.select_for_update(of=("self",))
                .select_related(None)
                .only("id", "team_id", "source_type", "job_inputs")
                .filter(pk=source.pk)
                .first()
            )
            if fresh is None:
                return True
            fresh_inputs = SourceInputsStore.load_stored(fresh)
            if is_stripped(fresh_inputs):
                raise _SourceStrippedMeanwhile()
            fresh_fields = split_connection_fields(str(fresh.source_type), fresh_inputs)
            if not connection_fields_equal(fresh_fields, fields):
                WarehouseSourceCredentialsStore.upsert(fresh, fresh_fields)
    except _SourceStrippedMeanwhile:
        return False
    return True


def _check_stripped(sources: list[ExternalDataSource], counts: BackfillCounts) -> None:
    # Never write the row of a stripped source from `job_inputs`: that would replace the credentials with nothing.
    if not sources:
        return
    stored = WarehouseSourceCredentialsStore.get_many(sources)
    for source in sources:
        row = stored.get(source.id)
        outcome = SKIPPED_STRIPPED if isinstance(row, dict) else STRIPPED_ROW_MISSING
        counts[(str(source.source_type), outcome)] += 1


def _orphans_of(refs: list[CredentialRowRef]) -> list[CredentialRowRef]:
    ids_by_team: dict[int, set[UUID]] = {}
    for ref in refs:
        try:
            ids_by_team.setdefault(ref.team_id, set()).add(UUID(ref.source_id))
        except ValueError:
            continue
    live: set[tuple[int, str]] = set()
    for team_id, ids in ids_by_team.items():
        live_ids = (
            ExternalDataSource.objects.exclude(deleted=True)
            .select_related(None)
            .filter(team_id=team_id, id__in=ids)
            .values_list("id", flat=True)
        )
        live.update((team_id, str(source_id)) for source_id in live_ids)
    return [ref for ref in refs if (ref.team_id, ref.source_id) not in live]
