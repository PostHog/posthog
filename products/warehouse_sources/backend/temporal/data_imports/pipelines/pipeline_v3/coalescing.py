"""Which queued batches the Delta sink may load as one commit.

The consumer plans sets from the batches it claimed, in claim order, and the processor checks a
set once more before it writes. Both read the rules from here so they cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.conf import settings

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import (
        ExportSignalMessage,
    )
    from products.warehouse_sources_queue.backend.core.jobs_db import PendingBatch

# CDC batches resolve positions against the table between writes, and a batch bound for external
# destinations is delivered per batch, so neither is folded into a set.
COALESCABLE_SYNC_TYPES: frozenset[str] = frozenset({"incremental", "append", "full_refresh"})
# A full refresh starts over at batch 0 and appends after it, so its runs never share a write.
CROSS_RUN_SYNC_TYPES: frozenset[str] = frozenset({"incremental", "append"})
# The loader holds a set decoded in Arrow through the upsert. Deduplication copies the rows only when
# a key repeats, and the loader frees the set as read before the upsert, so one copy is held.
_ARROW_COPIES_HELD = 1
_MB = 1024 * 1024


@frozen
class LoadShape:
    """The load configuration every member of a set must share.

    A set is written under its head's configuration, so a member whose keys, partitioning or
    first-sync flag differ would be merged the wrong way.
    """

    sync_type: str
    resource_name: str
    primary_keys: tuple[str, ...] | None
    partition_keys: tuple[str, ...] | None
    partition_count: int | None
    partition_size: int | None
    partition_mode: str | None
    partition_format: str | None
    is_first_ever_sync: bool
    cdc_write_mode: str | None
    # The external destinations the batch is delivered to, as a key rather than a flag: two
    # batches bound for different destinations are written under different configurations and
    # must never share a set, the same as two batches with different primary keys.
    external_destination_ids: tuple[str, ...]
    # A run's replace scope is applied by its first batch, so batches with different scopes, which
    # are batches of different runs, never share a write.
    replace_scope_manifest: str | None = None


@frozen
class CoalesceMember:
    """What the rules need to know about one queued batch."""

    team_id: int
    schema_id: str
    run_uuid: str
    job_id: str
    batch_index: int
    is_resume: bool
    row_count: int
    byte_size: int
    # Decoded Arrow size the producer recorded. None for a batch queued without it.
    arrow_bytes: int | None
    shape: LoadShape

    @classmethod
    def from_batch(cls, batch: PendingBatch) -> CoalesceMember:
        metadata = batch.metadata
        return cls(
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            run_uuid=batch.run_uuid,
            job_id=batch.job_id,
            batch_index=batch.batch_index,
            is_resume=batch.is_resume,
            row_count=batch.row_count,
            byte_size=batch.byte_size,
            arrow_bytes=_arrow_bytes(metadata.get("arrow_bytes")),
            shape=LoadShape(
                sync_type=batch.sync_type,
                resource_name=batch.resource_name,
                primary_keys=_key_tuple(metadata.get("primary_keys")),
                partition_keys=_key_tuple(metadata.get("partition_keys")),
                partition_count=metadata.get("partition_count"),
                partition_size=metadata.get("partition_size"),
                partition_mode=metadata.get("partition_mode"),
                partition_format=metadata.get("partition_format"),
                is_first_ever_sync=batch.is_first_ever_sync,
                cdc_write_mode=metadata.get("cdc_write_mode"),
                external_destination_ids=_external_ids(metadata.get("external_destination_ids"), batch.destination_ids),
                replace_scope_manifest=_manifest_path(metadata.get("replace_scope")),
            ),
        )

    @classmethod
    def from_signal(cls, signal: ExportSignalMessage) -> CoalesceMember:
        return cls(
            team_id=signal.team_id,
            schema_id=signal.schema_id,
            run_uuid=signal.run_uuid,
            job_id=signal.job_id,
            batch_index=signal.batch_index,
            is_resume=signal.is_resume,
            row_count=signal.row_count,
            byte_size=signal.byte_size,
            # The sink checks only the join rules, which never read a size.
            arrow_bytes=None,
            shape=LoadShape(
                sync_type=signal.sync_type,
                resource_name=signal.resource_name,
                primary_keys=_key_tuple(signal.primary_keys),
                partition_keys=_key_tuple(signal.partition_keys),
                partition_count=signal.partition_count,
                partition_size=signal.partition_size,
                partition_mode=signal.partition_mode,
                partition_format=signal.partition_format,
                is_first_ever_sync=signal.is_first_ever_sync,
                cdc_write_mode=signal.cdc_write_mode,
                external_destination_ids=_external_ids(signal.external_destination_ids, signal.destination_ids),
                replace_scope_manifest=signal.replace_scope.manifest_path if signal.replace_scope else None,
            ),
        )


@frozen
class CoalesceCaps:
    """The size a set may grow to. Rows and bytes are the real bounds; the count is a backstop.

    `max_arrow_bytes` bounds the decoded size of a set whose members all recorded it. A set with a
    member of unknown size, or a pod whose memory slice is unknown, is bounded by `max_bytes` of
    parquet on disk instead.
    """

    max_batches: int
    max_rows: int
    max_bytes: int
    max_arrow_bytes: int | None

    @classmethod
    def from_settings(cls, slot_budget_mb: float | None) -> CoalesceCaps:
        """`slot_budget_mb` is the memory slice the governor gives one upsert, or None when unknown."""
        return cls(
            max_batches=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_BATCHES,
            max_rows=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_ROWS,
            max_bytes=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_BYTES,
            max_arrow_bytes=_arrow_budget(slot_budget_mb),
        )


def _arrow_budget(slot_budget_mb: float | None) -> int | None:
    if slot_budget_mb is None or slot_budget_mb <= 0:
        return None
    held_bytes = slot_budget_mb * _MB * settings.DATA_WAREHOUSE_V3_COALESCE_SLOT_SHARE
    return min(int(held_bytes / _ARROW_COPIES_HELD), settings.DATA_WAREHOUSE_V3_COALESCE_MAX_ARROW_BYTES)


def _arrow_bytes(value: object) -> int | None:
    # The metadata is free-form JSON, so a value of any other shape counts as unknown.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _manifest_path(raw: object) -> str | None:
    path = raw.get("manifest_path") if isinstance(raw, dict) else None
    return path if isinstance(path, str) else None


def _key_tuple(keys: Sequence[str] | None) -> tuple[str, ...] | None:
    return None if keys is None else tuple(keys)


def _external_ids(external: Sequence[str] | None, snapshot: Sequence[str] | None) -> tuple[str, ...]:
    """The batch's external destinations, from the run's whole set when it carries no subset.

    A batch queued before the producer started recording the subset has no way to say which of
    its ids is the warehouse, so every id counts. That keeps such a batch out of every set,
    exactly as it was before, rather than guessing it has none and folding it into a write that
    would skip its per-batch delivery.
    """
    return tuple(snapshot or ()) if external is None else tuple(external)


def loadable_in_set(shape: LoadShape) -> bool:
    return (
        shape.sync_type in COALESCABLE_SYNC_TYPES
        and shape.cdc_write_mode is None
        and not shape.external_destination_ids
    )


def join_violation(current: Sequence[CoalesceMember], candidate: CoalesceMember) -> str | None:
    """Why `candidate` cannot follow `current` in one write, or None when it can.

    `current` is in load order. The rules only look at the sequence, never reorder it, so a set's
    members are written in exactly the order the loader would have taken them one at a time.
    """
    tail = current[-1]
    if not (loadable_in_set(tail.shape) and loadable_in_set(candidate.shape)):
        return "sync type, CDC mode or destinations are loaded one batch at a time"
    if (candidate.team_id, candidate.schema_id) != (tail.team_id, tail.schema_id):
        return "batches belong to different tables"
    if candidate.shape != tail.shape:
        return "batches are loaded under different configurations"
    if candidate.run_uuid == tail.run_uuid:
        if candidate.job_id != tail.job_id:
            return "batches of one run belong to different jobs"
        if candidate.batch_index != tail.batch_index + 1:
            return "batch indexes are not consecutive"
        return None
    if candidate.shape.sync_type not in CROSS_RUN_SYNC_TYPES:
        return f"{candidate.shape.sync_type} batches never share a write across runs"
    if candidate.batch_index == 0 and not candidate.is_resume:
        # A fresh run's first batch may overwrite the table, and only the head of a set overwrites.
        return "a fresh run starts its own write"
    if any(member.run_uuid == candidate.run_uuid for member in current):
        return "a run reappears after another run"
    return None


def extends_set(current: Sequence[CoalesceMember], candidate: CoalesceMember, caps: CoalesceCaps) -> bool:
    if join_violation(current, candidate) is not None:
        return False
    if len(current) >= caps.max_batches:
        return False
    members = [*current, candidate]
    if sum(member.row_count for member in members) > caps.max_rows:
        return False
    arrow_sizes = [member.arrow_bytes for member in members if member.arrow_bytes is not None]
    if caps.max_arrow_bytes is not None and len(arrow_sizes) == len(members):
        return sum(arrow_sizes) <= caps.max_arrow_bytes
    return sum(member.byte_size for member in members) <= caps.max_bytes


def set_violation(members: Sequence[CoalesceMember]) -> str | None:
    """Why `members` cannot be one write, or None. Checked by the sink before it reads anything."""
    if not members:
        return "the set is empty"
    if not loadable_in_set(members[0].shape):
        return "sync type, CDC mode or destinations are loaded one batch at a time"
    for position in range(1, len(members)):
        violation = join_violation(members[:position], members[position])
        if violation is not None:
            return violation
    return None


def runs_in_order(members: Sequence[CoalesceMember]) -> list[str]:
    """The distinct runs of a set, in load order."""
    runs: list[str] = []
    for member in members:
        if member.run_uuid not in runs:
            runs.append(member.run_uuid)
    return runs
