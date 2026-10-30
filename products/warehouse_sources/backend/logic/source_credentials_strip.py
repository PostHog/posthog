"""Strip the connection fields from the `job_inputs` of warehouse sources, restore them, and prune the backups.

A strip is the last step of the move of connection fields to the credentials rows. After it, the row is the
only storage of the credentials, so the strip runs only for a source whose reference points at a row that
verifies, and it writes a backup of the full `job_inputs` first. A source without a reference is refused:
run the backfill first. A source with an OAuth connection has nothing to strip. Each source is locked while it changes, so a concurrent write either
runs before the check or replaces the stripped value with a full one, which a later run strips again.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.contracts import CREDENTIALS_REFERENCE_KEY, UnreadableSourceInputsError
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    connection_fields_equal,
    is_stripped,
    read_enabled,
    split_connection_fields,
    stripped_at_now,
)
from products.warehouse_sources.backend.logic.source_credentials_sync import next_source_batch, stored_connection_fields
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.source_inputs_backup import ExternalDataSourceInputsBackup

logger = structlog.get_logger(__name__)

STRIPPED = "stripped"
ALREADY_STRIPPED = "already_stripped"
SKIPPED_READ_FLAG_OFF = "skipped_read_flag_off"
SKIPPED_NO_ROW_NEEDED = "skipped_no_row_needed"
SKIPPED_NO_REFERENCE = "skipped_no_reference"
SKIPPED_MISSING_ROW = "skipped_missing_row"
SKIPPED_UNREADABLE_ROW = "skipped_unreadable_row"
SKIPPED_ROW_DIFFERS = "skipped_row_differs"
SKIPPED_UNREADABLE_INPUTS = "skipped_unreadable_inputs"
SKIPPED_UNKNOWN_TYPE = "skipped_unknown_type"
SKIPPED_GONE = "skipped_gone"
FAILED = "failed"

RESTORED_FROM_ROW = "restored_from_row"
RESTORED_FROM_BACKUP = "restored_from_backup"
NOT_STRIPPED = "not_stripped"
NO_CREDENTIALS = "no_row_and_no_backup"

# Counts keyed by (source_type, outcome).
OutcomeCounts = Counter[tuple[str, str]]


@frozen
class PruneResult:
    matched: int
    deleted: int


def strip_connection_fields(
    *,
    execute: bool,
    batch_size: int = 200,
    team_ids: Sequence[int] = (),
    source_type: str | None = None,
    limit: int | None = None,
    on_batch: Callable[[int], None] | None = None,
) -> OutcomeCounts:
    """Strip each non-deleted source that passes all checks. With ``execute`` false, only count.

    The checks, in order: the read flag is on for the team, `job_inputs` decodes and is not stripped, the source
    has typed-in connection fields, `job_inputs` holds a credentials reference, and the row it points at exists,
    is readable and holds the same connection fields as `job_inputs`. Then the backup is written (an existing
    backup is kept), and then `job_inputs` keeps only its references, selectors, settings and runtime state.
    """
    counts: OutcomeCounts = Counter()
    last_id: UUID | None = None
    remaining = limit
    while remaining is None or remaining > 0:
        page_size = batch_size if remaining is None else min(batch_size, remaining)
        batch = next_source_batch(last_id, page_size, team_ids, source_type)
        if not batch:
            break
        last_id = batch[-1].id
        for source in batch:
            counts[(str(source.source_type), _strip_one(source, execute))] += 1
        if on_batch:
            on_batch(len(batch))
        if remaining is not None:
            remaining -= len(batch)
    return counts


def restore_connection_fields(
    *,
    execute: bool,
    source_ids: Sequence[UUID] = (),
    team_ids: Sequence[int] = (),
    prefer_backup: bool = False,
) -> OutcomeCounts:
    """Put full inputs back in the `job_inputs` of stripped sources and remove the strip marker.

    The connection fields come from the credentials row, because it holds every change made after the strip,
    such as a refreshed token. When the row is missing or unreadable, or with ``prefer_backup``, they come
    from the backup, and the row is written from the backup too. The sync settings and runtime state always
    come from the current `job_inputs`. The backup stays until the prune deletes it.
    """
    if not source_ids and not team_ids:
        raise ValueError("Give source ids or team ids to restore")
    queryset = ExternalDataSource.objects.exclude(deleted=True).select_related(None).order_by("id")
    if source_ids:
        queryset = queryset.filter(id__in=list(source_ids))
    if team_ids:
        queryset = queryset.filter(team_id__in=list(team_ids))

    counts: OutcomeCounts = Counter()
    for source_id, team_id, source_type in queryset.values_list("id", "team_id", "source_type"):
        try:
            outcome = _restore_one(source_id, team_id, execute, prefer_backup)
        except Exception:
            logger.exception("warehouse_source_credentials.restore_failed", source_id=str(source_id))
            outcome = FAILED
        counts[(str(source_type), outcome)] += 1
    return counts


def prune_backups(*, execute: bool, older_than_days: int, batch_size: int = 1000) -> PruneResult:
    """Delete backups older than ``older_than_days``. With ``execute`` false, only count them."""
    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")
    cutoff = timezone.now() - timedelta(days=older_than_days)
    # Backups of every team expire on the same rule, so this is a deliberate cross-team query.
    expired = ExternalDataSourceInputsBackup.objects.unscoped().filter(created_at__lt=cutoff)
    matched = expired.count()
    if not execute:
        return PruneResult(matched=matched, deleted=0)
    deleted = 0
    while True:
        ids = list(expired.order_by("id").values_list("id", flat=True)[:batch_size])
        if not ids:
            break
        # nosemgrep: idor-lookup-without-team (operator-only prune; backups of every team expire on the same rule)
        count, _ = ExternalDataSourceInputsBackup.objects.unscoped().filter(id__in=ids).delete()
        deleted += count
    return PruneResult(matched=matched, deleted=deleted)


def _strip_one(source: ExternalDataSource, execute: bool) -> str:
    if not read_enabled(source.team_id):
        return SKIPPED_READ_FLAG_OFF
    if not execute:
        outcome, _ = _check(source)
        return outcome
    try:
        with transaction.atomic():
            locked = _lock(source.id, source.team_id)
            if locked is None:
                return SKIPPED_GONE
            outcome, stored_inputs = _check(locked)
            if outcome != STRIPPED or stored_inputs is None:
                return outcome
            # A strip after a restore replaces the backup: an older backup can hold rotated-out credentials,
            # and the backup window counts from the last strip.
            ExternalDataSourceInputsBackup.objects.for_team(locked.team_id).update_or_create(
                source_id=locked.id,
                defaults={
                    "team_id": locked.team_id,
                    "source_type": str(locked.source_type),
                    "inputs": stored_inputs,
                    "created_at": timezone.now(),
                },
            )
            SourceInputsStore.write_stripped(locked, stripped_at=stripped_at_now())
    except Exception:
        logger.exception("warehouse_source_credentials.strip_failed", source_id=str(source.id))
        return FAILED
    return STRIPPED


def _check(source: ExternalDataSource) -> tuple[str, dict[str, Any] | None]:
    """The strip outcome of the source, and its stored `job_inputs` when it can be stripped."""
    try:
        stored_inputs = SourceInputsStore.load_stored(source)
    except UnreadableSourceInputsError:
        return SKIPPED_UNREADABLE_INPUTS, None
    if is_stripped(stored_inputs):
        return ALREADY_STRIPPED, None
    try:
        # Decrypted as the backfill wrote them, so a leaf with extra encryption layers still compares equal.
        expected = stored_connection_fields(source, stored_inputs)
    except UnreadableSourceInputsError:
        return SKIPPED_UNREADABLE_INPUTS, None
    except ValueError:
        return SKIPPED_UNKNOWN_TYPE, None
    if not expected or not has_typed_in_credentials(str(source.source_type)):
        return SKIPPED_NO_ROW_NEEDED, None
    ref = stored_inputs.get(CREDENTIALS_REFERENCE_KEY)
    if ref is None:
        return SKIPPED_NO_REFERENCE, None
    try:
        row = WarehouseSourceCredentialsStore.get(source, ref)
    except CredentialsUnreadableError:
        return SKIPPED_UNREADABLE_ROW, None
    if row is None:
        return SKIPPED_MISSING_ROW, None
    if not connection_fields_equal(row, expected):
        return SKIPPED_ROW_DIFFERS, None
    return STRIPPED, stored_inputs


def _restore_one(source_id: UUID, team_id: int, execute: bool, prefer_backup: bool) -> str:
    with transaction.atomic():
        source = _lock(source_id, team_id) if execute else _get(source_id, team_id)
        if source is None:
            return SKIPPED_GONE
        stored_inputs = SourceInputsStore.load_stored(source)
        if not is_stripped(stored_inputs):
            return NOT_STRIPPED

        ref = stored_inputs.get(CREDENTIALS_REFERENCE_KEY)
        connection: dict[str, Any] | None = None
        outcome = RESTORED_FROM_ROW
        if not prefer_backup:
            try:
                connection = WarehouseSourceCredentialsStore.get(source, ref)
            except CredentialsUnreadableError:
                connection = None
        if connection is None:
            backup = ExternalDataSourceInputsBackup.objects.for_team(source.team_id).filter(source_id=source.id).first()
            if backup is None:
                return NO_CREDENTIALS
            connection = split_connection_fields(str(source.source_type), backup.inputs)
            outcome = RESTORED_FROM_BACKUP
            if execute:
                # Credentials first, like every other write, so the row and `job_inputs` agree after the restore.
                ref = _write_backup_to_row(source, ref, connection)
        if execute:
            SourceInputsStore.write_restored(source, {**connection, **stored_inputs, CREDENTIALS_REFERENCE_KEY: ref})
    return outcome


def _write_backup_to_row(source: ExternalDataSource, ref: Any, connection: dict[str, Any]) -> int:
    """Write the backup to the row that ``ref`` points at, or to a new row when there is none. Returns its pk.

    A row that other objects also use raises `SharedCredentialsError`, so an old backup never changes their
    credentials without a person's decision.
    """
    if ref is not None:
        try:
            return WarehouseSourceCredentialsStore.update(source, ref, connection)
        except CredentialsNotFoundError:
            pass
    return WarehouseSourceCredentialsStore.create(source, connection)


def _lock(source_id: UUID, team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.select_for_update(of=("self",))
        .select_related(None)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "job_inputs", "prefix", "created_by_id")
        .filter(team_id=team_id, id=source_id)
        .first()
    )


def _get(source_id: UUID, team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.select_related(None)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "job_inputs", "prefix", "created_by_id")
        .filter(team_id=team_id, id=source_id)
        .first()
    )
