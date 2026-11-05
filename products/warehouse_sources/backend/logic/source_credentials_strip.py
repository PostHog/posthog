"""Strip the credentials from the `job_inputs` of warehouse sources, restore them, and prune the backups.

A strip is the last step of the move of credentials out of `job_inputs`. After it, the source's
`credentials_integration_id` column is the only storage of the row it uses:

- A source with typed-in credentials loses its connection fields. The strip runs only when the column points
  at a row that holds the same fields.
- An OAuth source loses its OAuth pointers (the in-use one and stale ones under options that are not
  selected). The strip runs only when the column holds the in-use pointer.

A source without a reference in its column is refused: run the backfill first. The strip writes a backup of
the full `job_inputs` first. Each source is locked while it changes, so a concurrent write either runs before
the check or replaces the stripped value with a full one, which a later run strips again.
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
from posthog.integrations import IntegrationReference

from products.warehouse_sources.backend.facade.contracts import (
    DEAD_CREDENTIALS_CLEARED_KEY,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    connection_fields_equal,
    in_use_oauth_slot,
    is_stripped,
    read_enabled,
    stripped_at_now,
)
from products.warehouse_sources.backend.logic.source_credentials_sync import next_source_batch, stored_connection_fields
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.source_inputs_backup import ExternalDataSourceInputsBackup
from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (
    OAuthPointerShapeError,
    pointer_at,
    with_pointer_at,
)

logger = structlog.get_logger(__name__)

STRIPPED = "stripped"
ALREADY_STRIPPED = "already_stripped"
SKIPPED_READ_FLAG_OFF = "skipped_read_flag_off"
SKIPPED_NO_ROW_NEEDED = "skipped_no_row_needed"
SKIPPED_NO_REFERENCE = "skipped_no_reference"
SKIPPED_MISSING_ROW = "skipped_missing_row"
SKIPPED_UNREADABLE_ROW = "skipped_unreadable_row"
SKIPPED_ROW_DIFFERS = "skipped_row_differs"
SKIPPED_REFERENCE_DIFFERS = "skipped_reference_differs"
SKIPPED_UNREADABLE_SHAPE = "skipped_unreadable_shape"
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

    The checks, in order: the read flag is on for the team, and `job_inputs` decodes and is not stripped. For an
    OAuth source, `job_inputs` holds an in-use pointer and the column holds the same row. For a source with
    typed-in connection fields, the column holds a reference, and the row it points at exists, is readable and
    holds the same connection fields as `job_inputs`. Then the backup is written (a strip after a restore
    replaces it), and then `job_inputs` loses its connection fields and its OAuth pointers.
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
        slot = in_use_oauth_slot(str(source.source_type), stored_inputs)
        if slot is not None:
            return _check_oauth(source, stored_inputs, slot), stored_inputs
        # Decrypted as the backfill wrote them, so a leaf with extra encryption layers still compares equal.
        expected = stored_connection_fields(source, stored_inputs)
    except OAuthPointerShapeError:
        return SKIPPED_UNREADABLE_SHAPE, None
    except UnreadableSourceInputsError:
        return SKIPPED_UNREADABLE_INPUTS, None
    except ValueError:
        return SKIPPED_UNKNOWN_TYPE, None
    if not expected or not has_typed_in_credentials(str(source.source_type)):
        return SKIPPED_NO_ROW_NEEDED, None
    if source.credentials_integration_id is None:
        return SKIPPED_NO_REFERENCE, None
    try:
        row = WarehouseSourceCredentialsStore.get(source)
    except CredentialsUnreadableError:
        return SKIPPED_UNREADABLE_ROW, None
    if row is None:
        return SKIPPED_MISSING_ROW, None
    if not connection_fields_equal(row, expected):
        return SKIPPED_ROW_DIFFERS, None
    return STRIPPED, stored_inputs


def _check_oauth(source: ExternalDataSource, stored_inputs: dict[str, Any], slot: tuple[str, ...]) -> str:
    pointer = pointer_at(stored_inputs, slot)
    if pointer is None:
        # No pointer is in use, so the column cannot be checked and nothing is in use to strip.
        return SKIPPED_NO_ROW_NEEDED
    if source.credentials_integration_id is None:
        return SKIPPED_NO_REFERENCE
    if source.credentials_integration_id != str(IntegrationReference.from_legacy_id(pointer.integration_id)):
        return SKIPPED_REFERENCE_DIFFERS
    return STRIPPED


def _restore_one(source_id: UUID, team_id: int, execute: bool, prefer_backup: bool) -> str:
    with transaction.atomic():
        source = _lock(source_id, team_id) if execute else _get(source_id, team_id)
        if source is None:
            return SKIPPED_GONE
        stored_inputs = SourceInputsStore.load_stored(source)
        if not is_stripped(stored_inputs):
            if DEAD_CREDENTIALS_CLEARED_KEY in stored_inputs:
                backup = _backup_of(source)
                if backup is None:
                    return NO_CREDENTIALS
                if execute:
                    SourceInputsStore.write_restored(source, backup.inputs)
                return RESTORED_FROM_BACKUP
            return NOT_STRIPPED
        slot = in_use_oauth_slot(str(source.source_type), stored_inputs)
        if slot is not None:
            return _restore_oauth(source, stored_inputs, slot, execute, prefer_backup)

        connection: dict[str, Any] | None = None
        outcome = RESTORED_FROM_ROW
        if not prefer_backup:
            try:
                connection = WarehouseSourceCredentialsStore.get(source)
            except CredentialsUnreadableError:
                connection = None
        if connection is None:
            backup = _backup_of(source)
            if backup is None:
                return NO_CREDENTIALS
            # Decrypted like the backfill and the strip check read them, so a leaf with an extra encryption layer
            # goes back as its value, not its ciphertext. An undecryptable leaf fails the restore.
            connection = stored_connection_fields(source, backup.inputs)
            outcome = RESTORED_FROM_BACKUP
            if execute:
                # Credentials first, like every other write, so the row and `job_inputs` agree after the restore.
                _write_backup_to_row(source, connection)
        if execute:
            SourceInputsStore.write_restored(source, {**connection, **stored_inputs})
    return outcome


def _restore_oauth(
    source: ExternalDataSource,
    stored_inputs: dict[str, Any],
    slot: tuple[str, ...],
    execute: bool,
    prefer_backup: bool,
) -> str:
    """Put the OAuth pointer of the column back at the path of the in-use OAuth field. The backup gives it when
    the column holds no legacy id, or with ``prefer_backup``, and then the column gets it too."""
    integration_id: int | None = None
    if not prefer_backup and source.credentials_integration_id is not None:
        try:
            integration_id = IntegrationReference.parse(source.credentials_integration_id).legacy_id
        except ValueError:
            integration_id = None
    outcome = RESTORED_FROM_ROW
    if integration_id is None:
        backup = _backup_of(source)
        pointer = pointer_at(backup.inputs, slot) if backup is not None else None
        if pointer is None:
            return NO_CREDENTIALS
        integration_id = pointer.integration_id
        outcome = RESTORED_FROM_BACKUP
        source.credentials_integration_id = str(IntegrationReference.from_legacy_id(integration_id))
    if execute:
        SourceInputsStore.write_restored(source, with_pointer_at(stored_inputs, slot, integration_id))
    return outcome


def _backup_of(source: ExternalDataSource) -> ExternalDataSourceInputsBackup | None:
    return ExternalDataSourceInputsBackup.objects.for_team(source.team_id).filter(source_id=source.id).first()


def _write_backup_to_row(source: ExternalDataSource, connection: dict[str, Any]) -> None:
    """Write the backup to the row that the column points at, or to a new row when there is none. Sets the
    column on the source.

    A row that other objects also use raises `SharedCredentialsError`, so an old backup never changes their
    credentials without a person's decision.
    """
    if source.credentials_integration_id is not None:
        try:
            WarehouseSourceCredentialsStore.update(source, connection)
            return
        except CredentialsNotFoundError:
            pass
    WarehouseSourceCredentialsStore.create(source, connection)


def _lock(source_id: UUID, team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.select_for_update(of=("self",))
        .select_related(None)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "job_inputs", "credentials_integration_id", "prefix", "created_by_id")
        .filter(team_id=team_id, id=source_id)
        .first()
    )


def _get(source_id: UUID, team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.select_related(None)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "job_inputs", "credentials_integration_id", "prefix", "created_by_id")
        .filter(team_id=team_id, id=source_id)
        .first()
    )
