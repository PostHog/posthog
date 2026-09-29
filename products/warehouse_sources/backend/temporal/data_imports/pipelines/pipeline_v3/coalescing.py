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
    has_destinations: bool


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
                has_destinations=bool(batch.destination_ids),
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
                has_destinations=bool(signal.destination_ids),
            ),
        )


@frozen
class CoalesceCaps:
    """The size a set may grow to. Rows and bytes are the real bounds; the count is a backstop."""

    max_batches: int
    max_rows: int
    max_bytes: int
    across_runs: bool

    @classmethod
    def from_settings(cls) -> CoalesceCaps:
        return cls(
            max_batches=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_BATCHES,
            max_rows=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_ROWS,
            max_bytes=settings.DATA_WAREHOUSE_V3_COALESCE_MAX_BYTES,
            across_runs=settings.DATA_WAREHOUSE_V3_COALESCE_ACROSS_RUNS,
        )


def _key_tuple(keys: Sequence[str] | None) -> tuple[str, ...] | None:
    return None if keys is None else tuple(keys)


def loadable_in_set(shape: LoadShape) -> bool:
    return shape.sync_type in COALESCABLE_SYNC_TYPES and shape.cdc_write_mode is None and not shape.has_destinations


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
    if candidate.run_uuid != current[-1].run_uuid and not caps.across_runs:
        return False
    if len(current) >= caps.max_batches:
        return False
    rows = sum(member.row_count for member in current) + candidate.row_count
    size = sum(member.byte_size for member in current) + candidate.byte_size
    return rows <= caps.max_rows and size <= caps.max_bytes


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
