"""A run that writes every table its source feeds, from one read of that source.

Kept apart from `PipelineV3` on purpose: every other source runs the base class, whose code is
the single-table path it has always been. Only a source that declares `SourceResponse.lanes`
gets this subclass, so nothing in here can change what a single-table run does.

Each table beyond the first gets its own `ExternalDataJob`, the way the legacy CDC extraction
already writes a `both` schema (see `cdc/activities.py`). That is what keeps the queue out of it:
a job is where batch idempotency, staging paths, claim ordering and completion all hang, so two
tables under one job would collide on every one of them, while two jobs are two ordinary
single-table runs the loader already knows how to finish.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from django.utils import timezone

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
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
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
        ImportJobModels,
    )


class _LaneWriter:
    """One table this run writes: its own job, its own staged files, its own count."""

    def __init__(
        self,
        lane: OutputLane,
        s3_batch_writer: S3BatchWriter,
        pg_producer: PostgresProducer,
        batch_results: list[BatchWriteResult] | None = None,
        job: ExternalDataJob | None = None,
    ) -> None:
        self.lane = lane
        self.s3_batch_writer = s3_batch_writer
        self.pg_producer = pg_producer
        self.batch_results: list[BatchWriteResult] = batch_results if batch_results is not None else []
        self.row_count = 0
        # None for the first lane, which writes the job the workflow already created for this run.
        self.job = job

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
        self._output_lanes = list(source_response.lanes)

        super().__init__(
            source_response, logger, job_id, reset_pipeline, shutdown_monitor, resumable_source_manager, models=models
        )

        # The base built the first lane; it shares the base's batch list so the two never disagree.
        primary = _LaneWriter(self._output_lanes[0], self._s3_batch_writer, self._pg_producer, self._batch_results)
        self._lane_writers = [primary]

    async def run(self) -> PipelineResult:
        await self._open_companion_lanes()
        completed = False
        try:
            result = await super().run()
            completed = True
            return result
        finally:
            if not completed:
                # Extraction raised, so no companion will send a final batch and nothing downstream
                # can finish its job. Shielded because the failure may be a cancellation.
                await asyncio.shield(self._fail_companion_jobs())

    async def _open_companion_lanes(self) -> None:
        """Give every table after the first its own job, writer and producer.

        A job per table rather than a suffix per lane: the loader completes a job when that job's
        final batch lands, so a table with its own job is finished, registered and post-loaded on
        its own terms. The companion carries no `workflow_run_id` — the schema's own job owns the
        pipeline lock, and a second holder releasing it would free it while this run still writes.
        It is not billable either: one read of a change stream is one sync however many tables it
        keeps.
        """
        for lane in self._output_lanes[1:]:
            job = await self._create_companion_job(lane)
            s3_batch_writer = self._build_s3_writer(f"{self._run_uuid}-cdc" if self._run_uuid else None)
            producer = PostgresProducer(
                **{
                    **self._producer_args(s3_batch_writer, resource_name=lane.name, cdc_write_mode=lane.cdc_write_mode),
                    "job_id": str(job.id),
                    "workflow_run_id": None,
                }
            )
            self._lane_writers.append(_LaneWriter(lane, s3_batch_writer, producer, job=job))

    async def _create_companion_job(self, lane: OutputLane) -> ExternalDataJob:
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
            _build_schema_snapshot,
        )

        def _create() -> ExternalDataJob:
            return ExternalDataJob.objects.create(
                team_id=self._job.team_id,
                pipeline_id=self._schema.source_id,
                schema_id=self._schema.id,
                status=ExternalDataJob.Status.RUNNING,
                rows_synced=0,
                workflow_id=self._job.workflow_id,
                workflow_run_id=None,
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
                billable=False,
                schema_snapshot={
                    **_build_schema_snapshot(self._schema),
                    # Distinguishes the two rows a `both` run produces, and names the run they
                    # belong to so a reader can tell whether the whole run finished.
                    "cdc_write_mode": lane.cdc_write_mode,
                    "companion_of": str(self._job.id),
                },
                destination_ids=list(self._job.destination_ids or []),
            )

        job = await database_sync_to_async_pool(_create)()
        await self._logger.ainfo(
            "companion_job_created", companion_job_id=str(job.id), resource_name=lane.name, job_id=str(self._job.id)
        )
        return job

    async def _fail_companion_jobs(self) -> None:
        """Take this run's companion jobs terminal when extraction failed.

        Nothing else would: the stranded sweep finds runs by their queued batches, so a companion
        that failed before staging anything has none to be found by, and its job would sit RUNNING
        for good.
        """
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
            mark_job_failed_if_not_terminal,
        )

        for writer in self._lane_writers:
            if writer.job is None:
                continue
            try:
                await database_sync_to_async_pool(mark_job_failed_if_not_terminal)(
                    job_id=str(writer.job.id),
                    team_id=self._job.team_id,
                    error="Extraction failed before this table's changes were written",
                )
            except Exception:
                await self._logger.awarning(
                    "companion_job_fail_write_failed", companion_job_id=str(writer.job.id), exc_info=True
                )

    async def _stage_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> int:
        # Each lane writes the same batch to its own job. A lane that already holds these rows
        # contributes nothing for this index, which leaves a gap in its batch indexes — the claim
        # gate orders on "no earlier index still running", so gaps are harmless.
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
                billable_rows += lane_table.num_rows
        return billable_rows

    def _total_batches(self) -> int:
        return sum(len(writer.batch_results) for writer in self._lane_writers)

    async def _send_final_batches(self, total_batches: int, row_count: int) -> str | None:
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
            )
            if writer.job is not None:
                await self._record_companion_rows(writer)
        return schema_path

    async def _finalize(self, row_count: int) -> None:
        # After the base, so a lane that did stage batches has already sent its final one. Runs on
        # the zero-batch path too, which returns before `_send_final_batches` is ever reached.
        await super()._finalize(row_count)
        for writer in self._lane_writers:
            if not writer.batch_results:
                await self._finish_empty_companion(writer)

    async def _finish_empty_companion(self, writer: _LaneWriter) -> None:
        """Complete a companion job whose table already held everything this run read.

        The loader completes a job when its final batch lands, and a lane that staged nothing
        sends none. Its own workflow cannot finalize it either — it only knows the schema's job —
        and the stranded sweep finds runs by their queued batches, so this one has nothing to be
        found by. Left alone it stays Running for good, and for a schema whose deletion proof
        waits on every table of a run, that also stops the buffer ever being cleaned up.
        """
        if writer.job is None:
            return
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

        job_id = writer.job.id
        try:
            await database_sync_to_async_pool(
                lambda: ExternalDataJob.objects.filter(id=job_id, status=ExternalDataJob.Status.RUNNING).update(
                    status=ExternalDataJob.Status.COMPLETED, rows_synced=0, finished_at=timezone.now()
                )
            )()
        except Exception:
            await self._logger.awarning("companion_job_not_completed", companion_job_id=str(job_id), exc_info=True)

    async def _record_companion_rows(self, writer: _LaneWriter) -> None:
        """Count what a companion wrote onto its own job, as the workflow does for the first."""
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

        assert writer.job is not None
        job_id, rows = writer.job.id, writer.row_count
        try:
            await database_sync_to_async_pool(
                lambda: ExternalDataJob.objects.filter(id=job_id).update(rows_synced=rows)
            )()
        except Exception:
            # Bookkeeping for rows already written; never worth failing the run over.
            await self._logger.awarning("companion_job_rows_not_recorded", companion_job_id=str(job_id), exc_info=True)

    def _mark_first_ever_sync(self) -> None:
        # The schema's own table only. A companion is append-only history the loader never
        # overwrites, and its own first write creates it.
        self._pg_producer.is_first_ever_sync = True

    def _close_producers(self) -> None:
        for writer in self._lane_writers:
            writer.pg_producer.close()
