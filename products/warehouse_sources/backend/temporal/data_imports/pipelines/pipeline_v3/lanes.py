"""A run that writes every table its source feeds, from one read of that source.

Kept apart from `PipelineV3` on purpose: every other source runs the base class, whose code is
the single-table path it has always been. Only a source that declares `SourceResponse.lanes`
gets this subclass, so nothing in here can change what a single-table run does.

Each lane is its own run in the load queue. The queue keys batch idempotency, staging paths and
claim ordering on the run id, so two tables sharing one would collide on all three; the lane's
suffix on the run id is what keeps them apart.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import (
    BatchWriteResult,
    S3BatchWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    OutputLane,
    ResumableData,
    SourceResponse,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
        ImportJobModels,
    )


class _LaneWriter:
    """One table this run writes: its own run in the queue, its own staged files, its own count."""

    def __init__(
        self,
        lane: OutputLane,
        s3_batch_writer: S3BatchWriter,
        pg_producer: PostgresProducer,
        batch_results: list[BatchWriteResult] | None = None,
    ) -> None:
        self.lane = lane
        self.s3_batch_writer = s3_batch_writer
        self.pg_producer = pg_producer
        self.batch_results: list[BatchWriteResult] = batch_results if batch_results is not None else []
        self.row_count = 0

    def prepare(self, pa_table: pa.Table) -> pa.Table:
        """This lane's share of a batch — the same rows unless it already holds some of them."""
        return self.lane.transform(pa_table) if self.lane.transform is not None else pa_table


class LanedPipelineV3(PipelineV3[ResumableData]):
    """`PipelineV3` for a source whose one stream lands in several tables."""

    _output_lanes: list[OutputLane]
    _lane_writers: list[_LaneWriter]

    def __init__(
        self,
        source_response: SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
        resumable_source_manager: ResumableSourceManager[ResumableData] | None,
        *,
        models: ImportJobModels,
    ) -> None:
        if not source_response.lanes:
            raise ValueError(f"{source_response.name} declares no lanes; run it on PipelineV3")
        # Read by the seams the base constructor calls, so it has to exist before super().__init__.
        self._output_lanes = list(source_response.lanes)

        super().__init__(
            source_response, logger, job_id, reset_pipeline, shutdown_monitor, resumable_source_manager, models=models
        )

        # The base built the first lane; it shares the base's batch list so the two never disagree.
        primary = _LaneWriter(self._output_lanes[0], self._s3_batch_writer, self._pg_producer, self._batch_results)
        self._lane_writers = [primary]
        for lane in self._output_lanes[1:]:
            s3_batch_writer = self._build_s3_writer(lane.run_uuid_suffix)
            producer = self._build_producer(
                s3_batch_writer, resource_name=lane.name, cdc_write_mode=lane.cdc_write_mode
            )
            self._lane_writers.append(_LaneWriter(lane, s3_batch_writer, producer))

    def _run_uuid_suffix(self) -> str:
        return self._output_lanes[0].run_uuid_suffix

    def _sibling_run_uuids(self) -> list[str]:
        """Every run id this attempt writes. Named on each producer so the first batch of one lane
        does not supersede its siblings, and on the final batch so completion waits for them all."""
        return [uuid for uuid in (self._run_uuid_for(lane.run_uuid_suffix) for lane in self._output_lanes) if uuid]

    async def _stage_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> int:
        # Each lane writes the same batch under its own run id. A lane that already holds these
        # rows contributes nothing for this index, which leaves a gap in its batch indexes — the
        # claim gate orders on "no earlier index still running", so gaps are harmless.
        billable_rows = 0
        for writer in self._lane_writers:
            lane_table = writer.prepare(pa_table)
            # Only a lane that filtered the batch away sits this index out. A batch that arrived
            # empty is still staged, as it is on a single-table run.
            if pa_table.num_rows and not lane_table.num_rows:
                continue
            writer.row_count += lane_table.num_rows
            batch_result = await asyncio.to_thread(writer.s3_batch_writer.write_batch, lane_table, batch_index)
            writer.batch_results.append(batch_result)
            writer.pg_producer.send_batch_notification(
                batch_result, is_final_batch=False, cumulative_row_count=writer.row_count
            )
            # One read of a change stream is one sync however many tables it keeps.
            if writer.lane.billable:
                billable_rows = lane_table.num_rows
        return billable_rows

    def _total_batches(self) -> int:
        return sum(len(writer.batch_results) for writer in self._lane_writers)

    async def _send_final_batches(self, total_batches: int, row_count: int) -> str | None:
        # Read after extraction, so it describes what this run actually consumed.
        extra_metadata = self._resource.finalize_metadata() if self._resource.finalize_metadata else None

        # Sent only now, with every lane's data batches already queued: the job completes on the
        # last final batch to land, and it must not land while another lane still has rows to write.
        schema_path = None
        for writer in self._lane_writers:
            if not writer.batch_results:
                continue
            lane_schema_path = await asyncio.to_thread(writer.s3_batch_writer.write_schema)
            schema_path = schema_path or lane_schema_path
            writer.pg_producer.send_batch_notification(
                writer.batch_results[-1],
                is_final_batch=True,
                total_batches=len(writer.batch_results),
                total_rows=writer.row_count,
                data_folder=writer.s3_batch_writer.get_data_folder(),
                schema_path=lane_schema_path,
                cumulative_row_count=writer.row_count,
                extra_metadata=extra_metadata,
            )
        return schema_path

    def _mark_first_ever_sync(self) -> None:
        for writer in self._lane_writers:
            writer.pg_producer.is_first_ever_sync = True

    def _close_producers(self) -> None:
        for writer in self._lane_writers:
            writer.pg_producer.close()
