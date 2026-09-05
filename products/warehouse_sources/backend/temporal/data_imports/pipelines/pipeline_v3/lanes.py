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


class LanedPipelineV3(PipelineV3[ResumableData]):
    """`PipelineV3` for a source whose one stream lands in several tables."""

    _output_lanes: list[OutputLane]
    _lane_writers: list[_LaneWriter]
    _writers_by_lane: dict[int, _LaneWriter]
    _companion_job_ids: list[str]

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
        # Companions are appended as they open; the primary is always here because the base built it.
        self._writers_by_lane: dict[int, _LaneWriter] = {id(self._output_lanes[0]): primary}
        # Tracked apart from the writers, so a job row this run created is retired even when the
        # writer built on top of it never came together.
        self._companion_job_ids = []

    async def run(self) -> PipelineResult:
        completed = False
        try:
            result = await super().run()
            completed = True
            return result
        finally:
            if not completed:
                # Only lanes that opened have a job, and none of them will send a final batch now.
                # Shielded because the failure may be a cancellation.
                await asyncio.shield(self._fail_companion_jobs())

    async def _writer_for(self, lane: OutputLane) -> _LaneWriter:
        """This lane's writer, opening its job on the first batch it actually has rows for.

        Opened lazily on purpose. A job created before there is anything to write is a row nothing
        owns: the loader finishes a job when its final batch lands, this activity's own workflow
        only knows the schema's job, and the stranded sweep finds runs by their queued batches. A
        crash between creating it and staging into it would leave it Running for good, and one such
        row blocks the flip and the rollback for the whole source. Opening it here means every
        companion job has at least one batch, so the sweep is its owner like any other run.
        """
        existing = self._writers_by_lane.get(id(lane))
        if existing is not None:
            return existing

        job = await self._create_companion_job(lane)
        # Recorded before the S3 client and the queue connect below, either of which can raise. A
        # job row this run loses track of is a row nothing retires, and one of those blocks the
        # flip and the rollback for the whole source.
        self._companion_job_ids.append(str(job.id))

        s3_batch_writer = self._build_s3_writer(self._companion_run_uuid())
        producer = PostgresProducer(
            **{
                **self._producer_args(s3_batch_writer, resource_name=lane.name, cdc_write_mode=lane.cdc_write_mode),
                "job_id": str(job.id),
                "workflow_run_id": None,
            }
        )
        writer = _LaneWriter(lane, s3_batch_writer, producer, job=job)
        self._writers_by_lane[id(lane)] = writer
        self._lane_writers.append(writer)
        return writer

    def _companion_run_uuid(self) -> str | None:
        return f"{self._run_uuid}-cdc" if self._run_uuid else None

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
        """Take this run's open companion jobs terminal when extraction did not finish.

        The row is written directly, the way the legacy CDC path retires its own companion jobs.
        Going through `update_external_job_status` would repaint the customer's schema FAILED and
        fire a failure digest, and this runs from a `finally` on every attempt — including ones
        Temporal retries and succeeds.

        Batches first, then the job, the order the reconcile sweep uses: a straggler that loads
        after the job went terminal would write rows the next run's read-back cannot account for.
        """

        for job_id in self._companion_job_ids:
            try:
                await asyncio.to_thread(self._retire_companion_batches, job_id)
            except Exception:
                await self._logger.awarning("companion_batches_not_failed", companion_job_id=job_id, exc_info=True)

            try:
                await database_sync_to_async_pool(self._retire_companion_job)(job_id)
            except Exception:
                await self._logger.awarning("companion_job_fail_write_failed", companion_job_id=job_id, exc_info=True)

    @staticmethod
    def _retire_companion_job(job_id: str) -> None:
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

        ExternalDataJob.objects.filter(id=job_id, status=ExternalDataJob.Status.RUNNING).update(
            status=ExternalDataJob.Status.FAILED,
            latest_error="Extraction ended before this table's changes were written",
            finished_at=timezone.now(),
        )

    @staticmethod
    def _retire_companion_batches(job_id: str) -> None:
        import psycopg

        from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
            BatchQueue,
        )

        with psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            BatchQueue.fail_batches_for_job_sync(
                conn, job_id=job_id, reason="extraction ended before this table's changes were written"
            )

    async def _stage_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> int:
        # Each lane writes the same batch to its own job. A lane that already holds these rows
        # contributes nothing for this index, which leaves a gap in its batch indexes — the claim
        # gate orders on "no earlier index still running", so gaps are harmless.
        billable_rows = 0
        for index, lane in enumerate(self._output_lanes):
            lane_table = lane.transform(pa_table) if lane.transform is not None else pa_table
            # Only a lane that filtered the batch away sits this index out. A batch that arrived
            # empty is still staged, as it is on a single-table run.
            #
            # The primary lane keeps index 0 whatever it filtered: the producer supersedes a
            # previous attempt's staged batches only on that index, so letting the merge lane skip
            # it would leave a retried run unable to retire what the attempt before it staged.
            filtered_away = pa_table.num_rows and not lane_table.num_rows
            if filtered_away and not (index == 0 and batch_index == 0):
                continue
            writer = await self._writer_for(lane)
            writer.row_count += lane_table.num_rows
            batch_result = await asyncio.to_thread(writer.s3_batch_writer.write_batch, lane_table, batch_index)
            writer.batch_results.append(batch_result)
            writer.pg_producer.send_batch_notification(
                batch_result, is_final_batch=False, cumulative_row_count=writer.row_count
            )
            # One read of a change stream is one sync however many tables it keeps.
            if lane.billable:
                billable_rows += lane_table.num_rows
        return billable_rows

    def _total_batches(self) -> int:
        return sum(len(writer.batch_results) for writer in self._lane_writers)

    def _consumer_finalizes_this_run(self) -> bool:
        # Only the primary lane's batches carry the schema's own job, and that job is the one the
        # workflow hands over. A companion's final batch completes a different job and releases no
        # lock, so counting it here would leave the schema's job Running and its lock held.
        return len(self._batch_results) > 0

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
