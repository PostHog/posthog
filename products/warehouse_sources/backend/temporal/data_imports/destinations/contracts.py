"""The contract every sync destination implements, PostHog's own warehouse included.

A run's staged parquet batches are delivered by one writer per destination. The consumer
engine is destination-agnostic: it claims a (batch, destination) work item, opens the staged
file, and hands the record batches to the writer resolved for that destination's type. The
few places the warehouse genuinely differs from an external destination are declared as
capabilities on the writer rather than branched on by the engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import field
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    import pyarrow as pa


@frozen
class DestinationRunContext:
    """Everything a writer needs that is fixed for the whole run.

    `config` and `integration_id` come from the destination snapshot taken when the run
    started, so a destination edited mid-run does not change where the run's remaining
    batches land.
    """

    team_id: int
    schema_id: str
    source_id: str
    job_id: str
    run_uuid: str
    destination_id: str
    destination_type: str
    destination_name: str
    # Fully qualified target name as the user's warehouse prefix resolves it.
    table_name: str
    sync_type: str
    primary_keys: tuple[str, ...] = ()
    config: dict = field(default_factory=dict)
    integration_id: int | None = None

    @property
    def is_full_refresh(self) -> bool:
        return self.sync_type == "full_refresh"

    @property
    def is_incremental(self) -> bool:
        return self.sync_type in ("incremental", "cdc")


@frozen
class DestinationBatchContext:
    """One batch's coordinates within its run."""

    run: DestinationRunContext
    batch_index: int
    is_final_batch: bool
    is_resume: bool = False
    # Rows the extractor recorded for this batch. Advisory: the writer reports what it wrote.
    expected_row_count: int | None = None

    @property
    def is_first_batch(self) -> bool:
        return self.batch_index == 0


@frozen
class BatchWriteOutcome:
    """What a writer actually delivered for one batch."""

    rows_written: int
    bytes_written: int = 0


@runtime_checkable
class DestinationWriter(Protocol):
    """Delivers a run's batches to one destination.

    Every method must be safe to call again after a crash or a lease loss: the engine
    re-claims a batch whose state it could not confirm, so `write_batch` in particular has
    to be idempotent per `batch_index` (merge on primary keys, delete-then-insert by batch
    index, or a deterministic object key).
    """

    # The v3 Redis sync lock is released when this writer's child job goes terminal. Only the
    # PostHog warehouse sets it: Delta table maintenance runs pre-extraction under that lock
    # and must not race in-flight writes. External destinations drain outside the lock so an
    # outage at one of them cannot block the schema's next scheduled sync.
    holds_sync_lock: ClassVar[bool] = False
    # This writer owns the post-load steps (table registration, queryable folder, post-import
    # workflow). Only the PostHog warehouse sets it — those steps describe a warehouse table.
    runs_post_load: ClassVar[bool] = False

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        """Create whatever the run writes into. Called before the run's first batch."""
        ...

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        """Apply one staged batch. Must be idempotent for a given `ctx.batch_index`."""
        ...

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Commit the run. Called once, after the final batch is applied."""
        ...

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        """Drop anything staged for a run that will not complete. Best effort."""
        ...
