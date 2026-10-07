import json
import asyncio
import inspect
import threading
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from asgiref.sync import async_to_sync

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.preemption import (
    PreemptionConfig,
    ShutdownStopwatch,
    SourcePreemptedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.abandonable_iterate import (
    SourceAbandonedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.handoff_checkpoint import (
    IncrementalBatchRangeReader,
    IncrementalHandoffCheckpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.lanes import (
    LanedPipelineV3,
    _LaneWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import (
    PipelineV3,
    should_coalesce_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.tests.test_resume_checkpoints import (
    paged_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    OutputLane,
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportJobModels,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_PIPELINE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline"
_SAFE_POINT = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point"
_LANES = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.lanes"
_CONSUMER = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer"
_PRODUCER = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer"


def _make_logger() -> MagicMock:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    logger.aexception = AsyncMock()
    logger.exception = MagicMock()
    return logger


def _make_pipeline() -> PipelineV3:
    """Build a PipelineV3 with just enough wiring to exercise run()."""
    with patch.object(PipelineV3, "__init__", return_value=None):
        pipeline = PipelineV3.__new__(PipelineV3)

    pipeline._resource = MagicMock(name="test_table", primary_keys=["id"], lanes=None)
    pipeline._resource_name = "test_table"
    pipeline._job = MagicMock(team_id=1, workflow_run_id="run-abc", billable=False)
    pipeline._source = MagicMock(source_type="Postgres")
    pipeline._schema = MagicMock(
        id="schema-1",
        source_id="source-1",
        is_incremental=False,
        is_webhook=False,
        is_append=False,
        table=None,
    )
    pipeline._table = None
    pipeline._logger = _make_logger()
    pipeline._is_incremental = False
    pipeline._reset_pipeline = False
    pipeline._delta_table_ref = MagicMock(is_first_sync=True)
    pipeline._resumable_source_manager = None
    pipeline._source_cursor_manager = None
    pipeline._internal_schema = MagicMock()
    pipeline._sinks = MagicMock(
        clear=AsyncMock(),
        stage_chunk=AsyncMock(),
        cdp_producer=MagicMock(should_run=AsyncMock(return_value=False)),
    )
    pipeline._batcher = MagicMock()
    pipeline._load_id = 1
    pipeline._s3_batch_writer = MagicMock()
    pipeline._pg_producer = MagicMock(sync_type="full_refresh")
    pipeline._batch_results = []
    pipeline._accumulated_pa_schema = None
    pipeline._shutdown_monitor = MagicMock()
    pipeline._attempt = 1
    pipeline._uses_delta_write_column_selection = False
    pipeline._observed_columns = {}
    pipeline._continues_incremental_handoff = False
    pipeline._resumed_incremental_run_uuid = None
    pipeline._sent_resumed_run_finalization = False

    return pipeline


class TestAttemptScopedRunUuid:
    def test_run_uuid_includes_attempt_number(self) -> None:
        mock_job = MagicMock(
            team_id=1,
            workflow_run_id="wfrun-abc",
            billable=False,
            id="job-1",
        )
        mock_schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=False,
            is_webhook=False,
            is_xmin=False,
            is_append=False,
            table=None,
            primary_key_columns=None,
            partition_count=None,
            partition_size=None,
            partitioning_keys=None,
            partition_format=None,
            partition_mode=None,
            incremental_field_earliest_value=None,
            incremental_field_type=None,
        )
        mock_source = MagicMock()
        mock_resource = MagicMock(
            name="test",
            primary_keys=["id"],
            partition_count=None,
            partition_size=None,
            partition_keys=None,
            partition_format=None,
            partition_mode=None,
            cdc_write_mode=None,
            lanes=None,
        )

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_import_attempt",
                return_value=3,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_workflow_id",
                return_value="wf-1",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_workflow_run_id",
                return_value="wfrun-abc",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.S3BatchWriter",
            ) as mock_s3_writer_cls,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.PostgresProducer",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.DeltaTableRef"
            ),
        ):
            mock_s3_writer_cls.return_value = MagicMock(get_run_uuid=MagicMock(return_value="wfrun-abc-a3"))
            pipeline: PipelineV3 = PipelineV3(
                source_response=mock_resource,
                logger=_make_logger(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                resumable_source_manager=None,
                models=ImportJobModels(job=mock_job, schema=mock_schema, source=mock_source, table=None),
            )

        assert pipeline._attempt == 3
        mock_s3_writer_cls.assert_called_once()
        assert mock_s3_writer_cls.call_args[0][3] == "wfrun-abc-a3"

    @pytest.mark.asyncio
    async def test_skips_reset_table_on_retry(self) -> None:
        pipeline = _make_pipeline()
        pipeline._attempt = 2
        pipeline._reset_pipeline = True

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.reset_rows_synced_if_needed",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.validate_incremental_sync",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.setup_row_tracking_with_billing_check",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.handle_reset_or_full_refresh",
                new_callable=AsyncMock,
            ) as mock_reset,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.activity",
            ) as mock_activity,
        ):
            mock_activity.in_activity.return_value = False
            pipeline._resource.items = MagicMock(return_value=iter([]))
            pipeline._batcher.should_yield.return_value = False  # type: ignore[attr-defined]

            await pipeline.run()

        mock_reset.assert_not_called()


class TestExtractionFailureDoesNotCleanupS3:
    @pytest.mark.asyncio
    async def test_s3_files_preserved_when_extraction_fails(self) -> None:
        pipeline = _make_pipeline()
        s3_writer = cast(MagicMock, pipeline._s3_batch_writer)
        pipeline._sinks = MagicMock(clear=AsyncMock(side_effect=RuntimeError("simulated extraction failure")))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.activity"
            ) as mock_activity,
        ):
            mock_activity.in_activity.return_value = False

            with pytest.raises(RuntimeError, match="simulated extraction failure"):
                await pipeline.run()

        s3_writer.cleanup.assert_not_called()


# Both properties below are silent when wrong: a `full_refresh` overwrites the customer's table
# with one micro-batch of changes, and a missing `cdc_write_mode` turns off enrichment and position
# resolution while every other test still passes.
class TestCDCSourceWiring:
    def _build(self, cdc_write_mode: str | None) -> tuple[PipelineV3, MagicMock]:
        mock_job = MagicMock(team_id=1, workflow_run_id="wfrun-abc", billable=False, id="job-1")
        mock_schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=False,
            is_webhook=False,
            is_xmin=False,
            is_append=False,
            table=None,
            primary_key_columns=["id"],
            partition_count=None,
            partition_size=None,
            partitioning_keys=None,
            partition_format=None,
            partition_mode=None,
            partition_count_override=None,
            partition_size_override=None,
            partitioning_keys_override=None,
            partition_mode_override=None,
        )
        mock_resource = MagicMock(
            name="users",
            primary_keys=["id"],
            partition_count=None,
            partition_size=None,
            partition_keys=None,
            partition_format=None,
            partition_mode=None,
            cdc_write_mode=cdc_write_mode,
            lanes=None,
        )

        base = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline"
        with (
            patch(f"{base}.current_import_attempt", return_value=1),
            patch(f"{base}.current_workflow_id", return_value="wf-1"),
            patch(f"{base}.current_workflow_run_id", return_value="wfrun-abc"),
            patch(f"{base}.S3BatchWriter"),
            patch(f"{base}.PostgresProducer") as mock_producer_cls,
            patch(f"{base}.DeltaTableRef"),
        ):
            pipeline: PipelineV3 = PipelineV3(
                source_response=mock_resource,
                logger=_make_logger(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                resumable_source_manager=None,
                models=ImportJobModels(
                    job=mock_job, schema=mock_schema, source=MagicMock(source_type="Postgres"), table=None
                ),
            )
        return pipeline, mock_producer_cls

    def test_a_cdc_run_writes_incrementally_and_carries_its_write_mode(self) -> None:
        pipeline, mock_producer_cls = self._build("incremental_merge")

        assert pipeline._is_incremental is True
        assert mock_producer_cls.call_args.kwargs["sync_type"] == "cdc"
        assert mock_producer_cls.call_args.kwargs["cdc_write_mode"] == "incremental_merge"

    def test_a_non_cdc_run_is_unaffected(self) -> None:
        pipeline, mock_producer_cls = self._build(None)

        assert pipeline._is_incremental is False
        assert mock_producer_cls.call_args.kwargs["sync_type"] == "full_refresh"
        assert mock_producer_cls.call_args.kwargs["cdc_write_mode"] is None


class TestCDCSeqProvenanceSurvivesStaging:
    def test_the_stamp_survives_every_extract_side_hop(self) -> None:
        # The loader gates all position resolution on the provenance stamp. If any hop between the
        # buffer read and the loader's parquet read strips field metadata, resolution silently turns
        # itself off: the floor never advances, files re-merge every run, and every other test still
        # passes. Chain mirrors PipelineV3.run: normalize → evolve against a Delta-derived schema
        # (which carries no arrow metadata) → batcher concat → staged-parquet round trip.
        import io

        import pyarrow as pa
        import deltalake
        import pyarrow.parquet as pq

        from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
            CDC_SEQ_COLUMN,
            CDC_SEQ_PROVENANCE,
        )
        from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import has_engine_seq
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
            evolve_pyarrow_schema,
            normalize_table_column_names,
        )

        table = pa.table({"id": pa.array([1, 2], pa.int64())}).append_column(
            pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE), pa.array([10, 20], pa.int64())
        )
        # The target as Delta reports it: same columns plus one this batch lacks, and no arrow
        # field metadata (Delta stores none), which is what could strip the stamp on evolve.
        target_fields: list[pa.Field] = [
            pa.field("id", pa.int64()),
            pa.field(CDC_SEQ_COLUMN, pa.int64()),
            pa.field("extra", pa.string()),
        ]
        delta_schema = deltalake.Schema.from_arrow(pa.schema(target_fields))

        staged = pa.concat_tables(
            [evolve_pyarrow_schema(normalize_table_column_names(table), delta_schema)] * 2,
            promote_options="permissive",
        )
        buf = io.BytesIO()
        pq.write_table(staged, buf)
        buf.seek(0)

        assert has_engine_seq(pq.read_table(buf))


def _build_laned(lanes) -> LanedPipelineV3:
    """A `LanedPipelineV3` over mocked collaborators, built the way the activity builds it."""
    mock_job = MagicMock(
        team_id=1, workflow_run_id="wfrun-abc", workflow_id="wf-1", billable=True, id="job-1", destination_ids=[]
    )
    mock_schema = MagicMock(
        id="schema-1",
        source_id="source-1",
        is_incremental=False,
        is_webhook=False,
        is_xmin=False,
        is_append=False,
        table=None,
        primary_key_columns=None,
        partition_count=None,
        partition_size=None,
        partitioning_keys=None,
        partition_format=None,
        partition_mode=None,
        incremental_field_earliest_value=None,
        incremental_field_type=None,
    )
    mock_resource = MagicMock(
        name="test",
        primary_keys=["id"],
        partition_count=None,
        partition_size=None,
        partition_keys=None,
        partition_format=None,
        partition_mode=None,
        cdc_write_mode=lanes[0].cdc_write_mode,
        lanes=lanes,
    )
    with (
        patch(f"{_PIPELINE}.current_import_attempt", return_value=3),
        patch(f"{_PIPELINE}.current_workflow_id", return_value="wf-1"),
        patch(f"{_PIPELINE}.current_workflow_run_id", return_value="wfrun-abc"),
        patch(f"{_PIPELINE}.S3BatchWriter"),
        patch(f"{_PIPELINE}.PostgresProducer"),
        patch(f"{_PIPELINE}.DeltaTableRef"),
    ):
        return LanedPipelineV3(
            source_response=mock_resource,
            logger=_make_logger(),
            job_id="job-1",
            reset_pipeline=False,
            shutdown_monitor=MagicMock(),
            resumable_source_manager=None,
            models=ImportJobModels(job=mock_job, schema=mock_schema, source=mock_source_stub(), table=None),
        )


def mock_source_stub() -> MagicMock:
    return MagicMock()


def _lane_writer(name: str, *, billable: bool = True, transform=None) -> _LaneWriter:
    s3_batch_writer = MagicMock(
        write_batch=MagicMock(side_effect=lambda t, i: MagicMock(batch_index=i)),
        write_schema=MagicMock(return_value=f"s3://schema/{name}"),
        get_data_folder=MagicMock(return_value=f"s3://data/{name}"),
    )
    return _LaneWriter(
        lane=OutputLane(name=name, billable=billable, transform=transform),
        s3_batch_writer=s3_batch_writer,
        pg_producer=MagicMock(sync_type="cdc"),
    )


@pytest.mark.asyncio
class TestLaneFanOut:
    @staticmethod
    def _pipeline(writers: list[_LaneWriter]) -> LanedPipelineV3:
        """A laned pipeline whose companion lanes are already open.

        Companions open lazily in production, on the first batch a lane has rows for. These tests
        are about the fan-out itself, so they hand the writers over ready-made; `TestCompanionJob`
        is what covers the opening.
        """
        base = _make_pipeline()
        pipeline = LanedPipelineV3.__new__(LanedPipelineV3)
        pipeline.__dict__.update(base.__dict__)
        pipeline._output_lanes = [writer.lane for writer in writers]
        pipeline._lane_writers = writers
        pipeline._writers_by_lane = dict(enumerate(writers))
        pipeline._s3_batch_writer = writers[0].s3_batch_writer
        pipeline._pg_producer = writers[0].pg_producer
        pipeline._batch_results = writers[0].batch_results
        cast(MagicMock, pipeline._schema).configure_mock(incremental_field=None, enabled_columns=None)
        pipeline._last_incremental_field_value = None
        pipeline._earliest_incremental_field_value = None
        return pipeline

    async def _process(self, pipeline: PipelineV3, table) -> MagicMock:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.update_incremental_field_values",
                AsyncMock(return_value=MagicMock(last_value=None, earliest_value=None)),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.update_row_tracking_after_batch",
                AsyncMock(),
            ) as tracked,
        ):
            await pipeline._process_batch(pa_table=table, batch_index=0, row_count=table.num_rows)
        return tracked

    async def test_every_lane_writes_the_batch(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", billable=False)]
        pipeline = self._pipeline(writers)

        await self._process(pipeline, pa.table({"id": pa.array([1, 2], pa.int64())}))

        assert [len(writer.batch_results) for writer in writers] == [1, 1]
        for writer in writers:
            cast(MagicMock, writer.pg_producer.hold_batch).assert_called_once()

    async def test_only_the_billable_lane_counts_towards_usage(self) -> None:
        # One read of a change stream is one sync however many tables it keeps.
        writers = [_lane_writer("users"), _lane_writer("users_cdc", billable=False)]
        pipeline = self._pipeline(writers)

        tracked = await self._process(pipeline, pa.table({"id": pa.array([1, 2, 3], pa.int64())}))

        assert tracked.call_args[0][3] == 3

    async def test_a_lane_that_already_holds_the_rows_stages_nothing_for_that_index(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", transform=lambda t: t.slice(0, 0))]
        pipeline = self._pipeline(writers)

        await self._process(pipeline, pa.table({"id": pa.array([1, 2], pa.int64())}))

        assert [len(writer.batch_results) for writer in writers] == [1, 0]
        cast(MagicMock, writers[1].pg_producer.hold_batch).assert_not_called()

    async def test_the_primary_lane_keeps_batch_zero_even_when_it_filters_it_away(self) -> None:
        # The producer supersedes a previous attempt's staged batches only on index 0. If the
        # merge lane could skip it, a retried run would never retire what the attempt before it
        # left staged, and those batches would load alongside this one.
        writers = [
            _lane_writer("users", transform=lambda t: t.slice(0, 0)),
            _lane_writer("users_cdc", billable=False),
        ]
        pipeline = self._pipeline(writers)

        await self._process(pipeline, pa.table({"id": pa.array([1, 2], pa.int64())}))

        assert [len(w.batch_results) for w in writers] == [1, 1]
        assert writers[0].row_count == 0

    async def test_a_batch_that_arrives_empty_is_staged_by_the_primary_lane_only(self) -> None:
        # Every non-CDC source is one lane with no transform, and reaches here with an empty table
        # whenever its source yields one. Skipping it would move job completion from the load
        # consumer to the workflow for those syncs. A companion has no job until it holds rows,
        # so staging the empty batch there would open one for nothing.
        writers = [_lane_writer("users"), _lane_writer("users_cdc", billable=False)]
        pipeline = self._pipeline(writers)

        await self._process(pipeline, pa.table({"id": pa.array([], pa.int64())}))

        assert [len(writer.batch_results) for writer in writers] == [1, 0]

    async def test_each_lane_ends_with_its_own_final_batch(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", billable=False)]
        pipeline = self._pipeline(writers)
        await self._process(pipeline, pa.table({"id": pa.array([1], pa.int64())}))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.finalize_desc_sort_incremental_value",
                AsyncMock(),
            ),
        ):
            await pipeline._finalize(row_count=1)

        for writer in writers:
            cast(MagicMock, writer.pg_producer.send_final_batch).assert_called_once()

    async def test_a_lane_with_nothing_to_write_sends_no_final_batch(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", transform=lambda t: t.slice(0, 0))]
        pipeline = self._pipeline(writers)
        await self._process(pipeline, pa.table({"id": pa.array([1], pa.int64())}))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.finalize_desc_sort_incremental_value",
                AsyncMock(),
            ),
        ):
            await pipeline._finalize(row_count=1)

        cast(MagicMock, writers[1].pg_producer.send_final_batch).assert_not_called()


class TestCompanionJob:
    """A table beyond the first gets its own job, opened only when it has rows to write."""

    @staticmethod
    def _laned(lanes: list[OutputLane]) -> LanedPipelineV3:
        return _build_laned(lanes)

    @staticmethod
    def _open(
        pipeline: LanedPipelineV3, lane: OutputLane, created: MagicMock, recorded: MagicMock | None = None
    ) -> MagicMock:
        producer = MagicMock()
        with (
            patch(f"{_LANES}.PostgresProducer", producer),
            patch(f"{_LANES}.record_companion_job", recorded or MagicMock()),
            patch(
                f"{_LANES}.database_sync_to_async_pool",
                lambda fn: AsyncMock(side_effect=lambda *a, **k: fn(*a, **k)),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.workflow_activities."
                "create_job_model._build_schema_snapshot",
                return_value={"name": "users"},
            ),
            patch("products.warehouse_sources.backend.models.external_data_job.ExternalDataJob.objects", created),
        ):
            async_to_sync(pipeline._writer_for)(pipeline._output_lanes.index(lane))
        return producer

    @staticmethod
    def _both() -> list[OutputLane]:
        return [
            OutputLane(name="users", cdc_write_mode="incremental_merge"),
            OutputLane(name="users_cdc", cdc_write_mode="scd2_append"),
        ]

    def test_no_job_is_created_until_a_lane_has_rows(self) -> None:
        # A job created before there is anything to write is a row nothing owns: the loader
        # finishes a job on its final batch, and the stranded sweep finds runs by their batches.
        pipeline = self._laned(self._both())

        assert len(pipeline._lane_writers) == 1
        assert pipeline._lane_writers[0].job is None

    def test_the_companion_table_gets_its_own_job(self) -> None:
        pipeline = self._laned(self._both())
        created = MagicMock()

        self._open(pipeline, pipeline._output_lanes[1], created)

        fields = created.create.call_args.kwargs
        # No workflow run id: the schema's own job owns the pipeline lock, and a second holder
        # releasing it would free it while this run is still writing.
        assert fields["workflow_run_id"] is None
        # One read of a change stream is one sync however many tables it keeps.
        assert fields["billable"] is False
        assert fields["schema_snapshot"]["cdc_write_mode"] == "scd2_append"
        assert fields["schema_snapshot"]["companion_of"] == "job-1"

    def test_the_parent_job_records_its_companion(self) -> None:
        # The listing proof checks companions by the ids on the parent's own row — a primary-key
        # lookup, where a search by `companion_of` would walk the schema's whole job history.
        pipeline = self._laned(self._both())
        created = MagicMock()
        created.create.return_value = MagicMock(id="companion-job")
        recorded = MagicMock()

        self._open(pipeline, pipeline._output_lanes[1], created, recorded)

        recorded.assert_called_once_with("job-1", pipeline._job.team_id, "companion-job", first_of_attempt=True)

    def test_the_companion_writes_under_its_own_job_and_run(self) -> None:
        pipeline = self._laned(self._both())
        created = MagicMock()
        created.create.return_value = MagicMock(id="companion-job")

        producer = self._open(pipeline, pipeline._output_lanes[1], created)

        assert producer.call_args.kwargs["job_id"] == "companion-job"
        assert producer.call_args.kwargs["workflow_run_id"] is None
        companion = pipeline._lane_writers[1].job
        assert companion is not None and companion.id == "companion-job"

    def test_a_lane_opens_once_however_many_batches_it_writes(self) -> None:
        pipeline = self._laned(self._both())
        created = MagicMock()
        created.create.return_value = MagicMock(id="companion-job")
        lane = pipeline._output_lanes[1]

        self._open(pipeline, lane, created)
        self._open(pipeline, lane, created)

        assert created.create.call_count == 1
        assert len(pipeline._lane_writers) == 2

    def test_the_schema_job_is_finalized_on_its_own_lane_alone(self) -> None:
        # Counting the companion's batches here would hand the schema's job to a consumer that
        # never hears about it, leaving the job Running and its pipeline lock held.
        pipeline = self._laned(self._both())
        companion = _lane_writer("users_cdc", billable=False)
        companion.batch_results.append(MagicMock(batch_index=0))
        pipeline._lane_writers.append(companion)

        assert pipeline._total_batches() == 1
        assert pipeline._consumer_finalizes_this_run() is False

    def test_a_failed_run_retires_its_companion_job_rows_and_nothing_else(self) -> None:
        # Keyed on the job id the run recorded, not on a writer: the row is created before the S3
        # client and the queue connect, and a failure between them must still retire it. Its
        # batches are left alone: failing one the loader is mid-write on does not stop the write,
        # but it does drop the run out of the in-flight guard, and the retry then reads a position
        # the straggler is about to move past and stages the same rows again.
        pipeline = self._laned(self._both())
        pipeline._companion_job_ids.append("companion-job")
        retired = MagicMock()

        with (
            patch(f"{_LANES}.retire_companion_job", retired),
            patch(
                f"{_LANES}.database_sync_to_async_pool",
                lambda fn: AsyncMock(side_effect=lambda *a, **k: fn(*a, **k)),
            ),
            patch(
                "products.warehouse_sources_queue.backend.core.jobs_db.BatchQueue.fail_batches_for_job_sync"
            ) as swept,
        ):
            async_to_sync(pipeline._fail_companion_jobs)()

        retired.assert_called_once_with("companion-job")
        swept.assert_not_called()

    def test_a_companion_whose_final_batch_is_queued_is_not_retired(self) -> None:
        # The loader owns it from there. Retiring it would have the loader discard a tail that
        # lands on its own, and show the customer a Failed history row for a run that succeeded.
        pipeline = self._laned(self._both())
        pipeline._companion_job_ids.extend(["done", "open"])
        pipeline._final_sent_job_ids.add("done")
        retired = MagicMock()

        with (
            patch(f"{_LANES}.retire_companion_job", retired),
            patch(
                f"{_LANES}.database_sync_to_async_pool", lambda fn: AsyncMock(side_effect=lambda *a, **k: fn(*a, **k))
            ),
        ):
            async_to_sync(pipeline._fail_companion_jobs)()

        retired.assert_called_once_with("open")

    @pytest.mark.asyncio
    async def test_a_history_only_schema_maintains_its_table_under_the_companion_watermark(self) -> None:
        # For `cdc_only` the schema's own table is the history table. The loader's post-load pass
        # vacuums it under `last_vacuum_version_cdc`; the pre-write pass here must use the same
        # one, or the two run on separate cadences against one table.
        pipeline = self._laned([OutputLane(name="users_cdc", cdc_write_mode="scd2_append")])
        pipeline._delta_table_ref = MagicMock(is_first_sync=False)
        pipeline._schema.table = MagicMock()
        pipeline._resource.items = MagicMock(return_value=iter([]))
        pipeline._sinks = MagicMock(clear=AsyncMock(), cdp_producer=MagicMock(should_run=AsyncMock(return_value=False)))
        maintenance = MagicMock()
        maintenance.return_value.run_scheduled = AsyncMock()

        with (
            patch(f"{_PIPELINE}.reset_rows_synced_if_needed", new_callable=AsyncMock),
            patch(f"{_PIPELINE}.validate_incremental_sync"),
            patch(f"{_PIPELINE}.setup_row_tracking_with_billing_check", new_callable=AsyncMock),
            patch(f"{_PIPELINE}.handle_reset_or_full_refresh", new_callable=AsyncMock),
            patch(f"{_PIPELINE}.DeltaMaintenance", maintenance),
            patch(f"{_PIPELINE}.activity") as mock_activity,
        ):
            mock_activity.in_activity.return_value = False
            await pipeline.run()

        assert maintenance.return_value.run_scheduled.call_args.kwargs["is_cdc_companion"] is True
        assert self._laned(self._both())._maintains_companion_table() is False

    def test_a_history_only_run_that_stands_down_still_maintains_under_the_companion_watermark(self) -> None:
        # The in-flight no-op declares no lanes and runs the base class over the same history
        # table. The answer has to come from the resource, not from the lanes.
        pipeline = _make_pipeline()
        pipeline._resource.cdc_write_mode = "scd2_append"

        assert pipeline._maintains_companion_table() is True

    def test_the_companion_delivers_to_no_destination(self) -> None:
        # Delivery names the destination table from the schema, so history rows merged by key
        # there would clobber the consolidated table's rows.
        pipeline = self._laned(self._both())
        pipeline._job.destination_ids = ["dest-1"]
        created = MagicMock()
        created.create.return_value = MagicMock(id="companion-job")

        producer = self._open(pipeline, pipeline._output_lanes[1], created)

        assert created.create.call_args.kwargs["destination_ids"] == []
        assert producer.call_args.kwargs["destination_ids"] == []


class TestSingleTableRunIsUntouched:
    """The base class is every non-lane source. Its staging path must not depend on lanes at all."""

    async def test_an_empty_batch_is_still_staged_and_counted(self) -> None:
        # A source that yields an empty table still stages it, which is what makes the load
        # consumer — not the workflow — complete the job.
        pipeline = _make_pipeline()
        pipeline._s3_batch_writer = MagicMock(write_batch=MagicMock(return_value=MagicMock(batch_index=0)))
        pipeline._pg_producer = MagicMock()
        pipeline._batch_results = []

        staged = await pipeline._stage_batch(pa.table({"id": pa.array([], pa.int64())}), 0, 0)

        assert staged == 0
        pipeline._s3_batch_writer.write_batch.assert_called_once()
        pipeline._pg_producer.hold_batch.assert_called_once()

    def test_the_activity_runs_the_base_class_for_a_source_without_lanes(self) -> None:
        # What keeps every other source off the subclass. `lanes=None` is what a source that
        # never heard of lanes carries, and `[]` what a lane build that found nothing returns.
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
            v3_pipeline_class,
        )

        assert v3_pipeline_class(MagicMock(lanes=None)) is PipelineV3
        assert v3_pipeline_class(MagicMock(lanes=[])) is PipelineV3
        assert v3_pipeline_class(MagicMock(lanes=[OutputLane(name="users_cdc")])) is LanedPipelineV3

    def test_the_laned_pipeline_takes_every_argument_the_base_takes(self) -> None:
        # The activity builds both classes with one call, so an argument added to the base
        # alone fails every run of a source with lanes.
        base = inspect.signature(PipelineV3.__init__).parameters
        laned = inspect.signature(LanedPipelineV3.__init__).parameters

        assert set(base) - set(laned) == set()


class TestFinalizeStagesTheWatermarkFirst:
    @pytest.mark.asyncio
    async def test_desc_watermark_is_staged_before_the_final_batch_notification(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = [MagicMock()]
        pipeline._last_incremental_field_value = None
        order: list[str] = []
        pipeline._send_final_batches = AsyncMock(side_effect=lambda *_a, **_k: order.append("send"))  # type: ignore[method-assign]

        with (
            patch(
                f"{_PIPELINE}.finalize_desc_sort_incremental_value",
                AsyncMock(side_effect=lambda *_a, **_k: order.append("stage")),
            ),
        ):
            await pipeline._finalize(row_count=1)

        assert order == ["stage", "send"]

    @pytest.mark.asyncio
    async def test_the_source_cursor_is_staged_for_the_loader_before_the_final_batch_notification(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = [MagicMock()]
        pipeline._last_incremental_field_value = None
        pipeline._s3_batch_writer = MagicMock(get_run_uuid=MagicMock(return_value="run-1"))
        payload = {"kind": "postgres_xmin", "data": {}}
        pipeline._source_cursor_manager = MagicMock(staged_payload=MagicMock(return_value=payload))
        order: list[str] = []
        schema = MagicMock()
        schema.stage_source_cursor.side_effect = lambda *_a: order.append("stage")
        pipeline._schema = schema
        pipeline._send_final_batches = AsyncMock(side_effect=lambda *_a, **_k: order.append("send"))  # type: ignore[method-assign]

        with patch(f"{_PIPELINE}.finalize_desc_sort_incremental_value", AsyncMock()):
            await pipeline._finalize(row_count=1)

        assert order == ["stage", "send"]
        schema.stage_source_cursor.assert_called_once_with("run-1", payload)
        schema.update_source_cursor.assert_not_called()


class TestZeroBatchRunStampsTheFullRunMarker:
    @pytest.mark.asyncio
    async def test_a_run_that_extracted_nothing_still_counts_as_a_full_run(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = []

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.update_sync_type_config_keys",
            new=MagicMock(),
        ) as update:
            await pipeline._finalize(row_count=0)

        update.assert_called_once()
        assert "last_full_run_at" in update.call_args.kwargs["updates"]
        assert "extra_model_fields" not in update.call_args.kwargs

    @pytest.mark.asyncio
    async def test_a_run_that_extracted_nothing_stores_its_source_cursor_directly(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = []
        payload = {"kind": "postgres_xmin", "data": {}}
        pipeline._source_cursor_manager = MagicMock(staged_payload=MagicMock(return_value=payload))
        schema = MagicMock()
        pipeline._schema = schema

        with patch(f"{_PIPELINE}.update_sync_type_config_keys", new=MagicMock()):
            await pipeline._finalize(row_count=0)

        schema.update_source_cursor.assert_called_once_with(payload)
        schema.stage_source_cursor.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_bookkeeping_failure_does_not_fail_the_sync(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = []

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.update_sync_type_config_keys",
            new=MagicMock(side_effect=RuntimeError("pooler is down")),
        ):
            await pipeline._finalize(row_count=0)


@dataclass(frozen=True)
class _Cursor:
    id: str


@dataclass(frozen=True)
class _PageCursor:
    page: int


def _manager() -> ResumableSourceManager[_Cursor]:
    inputs = cast(SourceInputs, SimpleNamespace(team_id=1, job_id="job-1", logger=MagicMock()))
    return ResumableSourceManager[_Cursor](inputs, _Cursor)


def _table_source(manager: ResumableSourceManager[_Cursor], ids: list[str], stage_before_yield: bool):
    def items():
        previous = None
        for row_id in ids:
            if stage_before_yield:
                manager.save_state(_Cursor(row_id))
            elif previous is not None:
                manager.save_state(_Cursor(previous))
            yield pa.table({"id": [row_id]})
            previous = row_id

    return items


def _runnable_pipeline(manager: ResumableSourceManager[_Cursor], items) -> PipelineV3:
    pipeline = _make_pipeline()
    pipeline._resumable_source_manager = manager
    pipeline._resource = SourceResponse(name="test_table", items=items, primary_keys=["id"])
    pipeline._batcher = Batcher(MagicMock(), primary_keys=["id"])
    pipeline._schema = MagicMock(
        id="schema-1",
        source_id="source-1",
        is_incremental=False,
        is_webhook=False,
        is_append=False,
        should_use_incremental_field=False,
        table=None,
    )
    pipeline._process_batch = AsyncMock()  # type: ignore[method-assign]
    return pipeline


def _raise_on_second_call(exc: Exception):
    calls = {"n": 0}

    def side_effect():
        calls["n"] += 1
        if calls["n"] == 2:
            raise exc

    return side_effect


async def _run_expecting(pipeline: PipelineV3, redis: MagicMock, exc: type[BaseException]) -> None:
    with ExitStack() as stack:
        stack.enter_context(patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)))
        for name in (
            "reset_rows_synced_if_needed",
            "setup_row_tracking_with_billing_check",
            "handle_reset_or_full_refresh",
            "handle_corrupted_delta_log",
        ):
            stack.enter_context(patch(f"{_PIPELINE}.{name}", new_callable=AsyncMock))
        for name in ("validate_incremental_sync", "record_source_item_stats"):
            stack.enter_context(patch(f"{_PIPELINE}.{name}"))
        stack.enter_context(patch(f"{_PIPELINE}.activity")).in_activity.return_value = False
        with pytest.raises(exc):
            await pipeline.run()


class TestShouldCoalesceTables:
    @pytest.mark.parametrize(
        "resume_manager,is_webhook,expected",
        [
            # The case the resolved manager exists for: a resumable source class whose current run
            # reports supports_resume=False resolves to no manager, commits no cursor, and so is free
            # to coalesce. Reading the raw manager here switched coalescing off for every run of every
            # resumable class instead.
            (None, False, True),
            (MagicMock(), False, False),
            (None, True, False),
            (MagicMock(), True, False),
        ],
        ids=["no_cursor_to_commit", "commits_a_cursor", "webhook", "webhook_and_cursor"],
    )
    def test_coalescing_is_off_exactly_when_a_yield_is_durable(self, resume_manager, is_webhook, expected):
        assert should_coalesce_tables(resume_manager=resume_manager, is_webhook=is_webhook) is expected


class TestResumeCursorCommit:
    @pytest.mark.parametrize(
        "stage_before_yield,expected_committed",
        [(True, ["a", "b"]), (False, ["a"])],
        ids=["staged_before_yield", "staged_after_yield"],
    )
    @pytest.mark.asyncio
    async def test_cursor_persisted_covers_exactly_the_staged_batches(
        self, stage_before_yield: bool, expected_committed: list[str]
    ) -> None:
        redis = MagicMock()
        manager = _manager()
        pipeline = _runnable_pipeline(manager, _table_source(manager, ["a", "b", "c"], stage_before_yield))
        shutdown = WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")
        cast(MagicMock, pipeline._shutdown_monitor).raise_if_is_worker_shutdown.side_effect = _raise_on_second_call(
            shutdown
        )

        await _run_expecting(pipeline, redis, WorkerShuttingDownError)

        assert cast(AsyncMock, pipeline._process_batch).await_count == 2
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == expected_committed

    @pytest.mark.parametrize("wrapped", [False, True], ids=["rest_resource", "wrapped_rest_resource"])
    @pytest.mark.asyncio
    async def test_a_rest_source_handed_off_after_its_first_batch_resumes_without_losing_rows(
        self, wrapped: bool
    ) -> None:
        redis = MagicMock()
        inputs = cast(SourceInputs, SimpleNamespace(team_id=1, job_id="job-1", logger=MagicMock()))
        manager = ResumableSourceManager[_PageCursor](inputs, _PageCursor)
        pages = {"/items": [[{"id": 1}], [{"id": 2}], [{"id": 3}]]}

        def rest_items(state: dict | None):
            resource = rest_api_resource(
                paged_config(pages, ["items"]),
                1,
                "job-1",
                None,
                resume_hook=lambda next_page: manager.save_state(_PageCursor(next_page["page"])) if next_page else None,
                initial_paginator_state=state,
            )
            return (lambda: (page for page in resource)) if wrapped else (lambda: resource)

        pipeline = _runnable_pipeline(cast(ResumableSourceManager[_Cursor], manager), rest_items(None))
        pipeline._batcher = Batcher(MagicMock(), chunk_size=1, primary_keys=["id"])
        cast(MagicMock, pipeline._shutdown_monitor).raise_if_is_worker_shutdown.side_effect = WorkerShuttingDownError(
            "id", "type", "queue", 1, "workflow", "workflow_type"
        )

        await _run_expecting(pipeline, redis, WorkerShuttingDownError)

        written = [
            row_id
            for call in cast(AsyncMock, pipeline._process_batch).await_args_list
            for row_id in call.kwargs["pa_table"]["id"].to_pylist()
        ]
        committed = [json.loads(call.args[1]) for call in redis.set.call_args_list]
        resumed = [row["id"] for page in rest_items(committed[-1] if committed else None)() for row in page]

        assert written == [1]
        if wrapped:
            assert set(written + resumed) == {1, 2, 3}
        else:
            assert committed == [{"page": 1}]
            assert written + resumed == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_cursor_not_persisted_for_rows_the_batcher_still_holds(self) -> None:
        redis = MagicMock()
        manager = _manager()

        def items():
            yield [{"id": "a"}]
            manager.save_state(_Cursor("a"))
            yield [{"id": "b"}]
            manager.save_state(_Cursor("b"))
            yield [{"id": "c"}]

        pipeline = _runnable_pipeline(manager, items)
        shutdown = WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")
        cast(MagicMock, pipeline._shutdown_monitor).raise_if_is_worker_shutdown.side_effect = _raise_on_second_call(
            shutdown
        )

        await _run_expecting(pipeline, redis, WorkerShuttingDownError)

        cast(AsyncMock, pipeline._process_batch).assert_not_awaited()
        redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_rows_buffered_when_the_source_raises_are_staged_with_their_cursor(self) -> None:
        redis = MagicMock()
        manager = _manager()

        def items():
            manager.save_state(_Cursor("a"))
            yield [{"id": "a"}]
            raise RuntimeError("page budget")

        pipeline = _runnable_pipeline(manager, items)

        await _run_expecting(pipeline, redis, RuntimeError)

        assert cast(AsyncMock, pipeline._process_batch).await_count == 1
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == ["a"]

    @pytest.mark.asyncio
    async def test_an_empty_page_safe_point_hands_off_at_shutdown_with_its_cursor(self) -> None:
        redis = MagicMock()
        manager = _manager()

        def items():
            manager.save_state(_Cursor("a"))
            yield [{"id": "a"}]
            for page in ("b", "c"):
                manager.save_state(_Cursor(page))
                manager.safe_point()

        pipeline = _runnable_pipeline(manager, items)
        shutdown = WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")
        cast(MagicMock, pipeline._shutdown_monitor).raise_if_is_worker_shutdown.side_effect = _raise_on_second_call(
            shutdown
        )

        await _run_expecting(pipeline, redis, WorkerShuttingDownError)

        assert cast(AsyncMock, pipeline._process_batch).await_count == 1
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == ["b"]

    @pytest.mark.asyncio
    async def test_empty_page_safe_points_commit_the_cursor_when_nothing_is_unwritten(self) -> None:
        redis = MagicMock()
        manager = _manager()

        def items():
            for page in ("a", "b"):
                manager.save_state(_Cursor(page))
                manager.safe_point()
            yield from ()
            raise RuntimeError("page budget")

        pipeline = _runnable_pipeline(manager, items)
        pipeline._pg_producer = _recording_producer()

        with patch(f"{_SAFE_POINT}.SAFE_POINT_COMMIT_INTERVAL_SECONDS", 0):
            await _run_expecting(pipeline, redis, RuntimeError)

        cast(AsyncMock, pipeline._process_batch).assert_not_awaited()
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == ["a", "b"]


def _recording_producer(events: list[str] | None = None, *, is_resume: bool = False) -> PostgresProducer:
    """A real producer over a mocked queue connection, so the rows it inserts can be read back."""
    with patch(f"{_PRODUCER}.psycopg") as mock_psycopg:
        conn = MagicMock()
        if events is not None:
            conn.execute.side_effect = lambda *_a, **_k: events.append("insert")
        mock_psycopg.Connection.connect.return_value = conn
        producer = PostgresProducer(
            database_url="postgres://unused:unused@localhost/unused",
            team_id=1,
            job_id="job-1",
            schema_id="schema-1",
            source_id="source-1",
            resource_name="test_table",
            sync_type="full_refresh",
            run_uuid="run-1",
            logger=MagicMock(),
            is_resume=is_resume,
        )
    return producer


def _queue_rows(producer: PostgresProducer) -> list[tuple[int, bool]]:
    return [
        (call.args[1]["batch_index"], call.args[1]["is_final_batch"])
        for call in cast(MagicMock, producer._conn.execute).call_args_list
        if "INSERT INTO" in call.args[0]
    ]


class TestFinalMarkerIsTheLastDataRow:
    """The loader processes every queue row. A final marker that repeats the last data batch makes it
    read and open that batch twice, and a marker that goes missing leaves the run running forever."""

    def _staging_pipeline(self, ids: list[str], manager: ResumableSourceManager[_Cursor] | None = None) -> PipelineV3:
        pipeline = _make_pipeline()
        pipeline._pg_producer = _recording_producer()
        pipeline._resumable_source_manager = manager
        pipeline._last_incremental_field_value = None
        pipeline._batcher = Batcher(MagicMock(), primary_keys=["id"])
        pipeline._schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=False,
            is_webhook=False,
            is_append=False,
            should_use_incremental_field=False,
            table=None,
        )
        pipeline._s3_batch_writer = MagicMock(
            write_batch=MagicMock(
                side_effect=lambda table, index: BatchWriteResult(
                    s3_path=f"s3://data/{index}.parquet",
                    row_count=table.num_rows,
                    byte_size=1,
                    batch_index=index,
                    timestamp_ns=0,
                )
            ),
            write_schema=MagicMock(return_value="s3://data/schema.json"),
            get_data_folder=MagicMock(return_value="s3://data"),
            get_run_uuid=MagicMock(return_value="run-1"),
        )

        def items():
            for row_id in ids:
                if manager is not None:
                    manager.save_state(_Cursor(row_id))
                yield pa.table({"id": [row_id]})

        pipeline._resource = SourceResponse(name="test_table", items=items, primary_keys=["id"])

        # Everything `_process_batch` does besides staging needs the app DB; staging is the part under test.
        async def stage_only(pa_table: pa.Table, batch_index: int, row_count: int) -> None:
            await pipeline._stage_batch(pa_table, batch_index, row_count)

        pipeline._process_batch = AsyncMock(side_effect=stage_only)  # type: ignore[method-assign]
        return pipeline

    async def _run(self, pipeline: PipelineV3, redis: MagicMock | None = None) -> None:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis or MagicMock()))
            )
            for name in (
                "reset_rows_synced_if_needed",
                "setup_row_tracking_with_billing_check",
                "handle_reset_or_full_refresh",
                "handle_corrupted_delta_log",
                "finalize_desc_sort_incremental_value",
            ):
                stack.enter_context(patch(f"{_PIPELINE}.{name}", new_callable=AsyncMock))
            for name in ("validate_incremental_sync", "record_source_item_stats", "update_sync_type_config_keys"):
                stack.enter_context(patch(f"{_PIPELINE}.{name}"))
            stack.enter_context(patch(f"{_PRODUCER}.BatchQueue.supersede_other_runs", return_value=0))
            stack.enter_context(patch(f"{_PIPELINE}.activity")).in_activity.return_value = False
            await pipeline.run()

    @pytest.mark.asyncio
    async def test_a_zero_batch_continuation_finalizes_the_earlier_queue_run(self) -> None:
        pipeline = _make_pipeline()
        pipeline._continues_incremental_handoff = True
        pipeline._resumed_incremental_run_uuid = "workflow-run-a1"

        await pipeline._finalize(row_count=0)

        cast(MagicMock, pipeline._pg_producer.send_final_batch_for_resumed_run).assert_called_once_with(
            "workflow-run-a1"
        )
        assert pipeline._consumer_finalizes_this_run() is True

    @pytest.mark.parametrize(
        "ids,expected_rows",
        [
            ([], []),
            (["a"], [(0, True)]),
            (["a", "b", "c"], [(0, False), (1, False), (2, True)]),
        ],
        ids=["zero_rows", "single_batch", "three_batches"],
    )
    @pytest.mark.asyncio
    async def test_a_run_enqueues_one_row_per_batch_with_the_last_one_final(
        self, ids: list[str], expected_rows: list[tuple[int, bool]]
    ) -> None:
        pipeline = self._staging_pipeline(ids)
        producer = pipeline._pg_producer

        await self._run(pipeline)

        assert _queue_rows(producer) == expected_rows

    @pytest.mark.asyncio
    async def test_a_resumable_source_enqueues_each_row_before_its_cursor_and_ends_with_a_marker(self) -> None:
        # Every cursor commit promises that the rows before it are loadable, so each held row goes in
        # before the commit that depends on it; the run then ends the old way, with the last batch
        # repeated as the final marker.
        events: list[str] = []
        manager = _manager()
        redis = MagicMock()
        redis.set.side_effect = lambda *_a, **_k: events.append("commit")
        pipeline = self._staging_pipeline(["a", "b"], manager)
        pipeline._pg_producer = _recording_producer(events)
        producer = pipeline._pg_producer

        await self._run(pipeline, redis)

        assert events == ["insert", "commit", "insert", "commit", "insert"]
        assert _queue_rows(producer) == [(0, False), (1, False), (1, True)]

    @pytest.mark.parametrize("staged", [True, False], ids=["cursor_staged", "nothing_staged"])
    @pytest.mark.asyncio
    async def test_a_cursor_commit_releases_the_held_row_first(self, staged: bool) -> None:
        events: list[str] = []
        manager = _manager()
        if staged:
            manager.save_state(_Cursor("a"))
        redis = MagicMock()
        redis.set.side_effect = lambda *_a, **_k: events.append("commit")
        pipeline = _make_pipeline()
        pipeline._pg_producer = _recording_producer(events)
        pipeline._resumable_source_manager = manager
        pipeline._pg_producer.hold_batch(
            BatchWriteResult(s3_path="s3://data/1.parquet", row_count=1, byte_size=1, batch_index=1, timestamp_ns=2),
            cumulative_row_count=2,
        )

        with patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)):
            await pipeline._commit_resume_state()

        assert events == (["insert", "commit"] if staged else [])

    @pytest.mark.asyncio
    async def test_an_extraction_error_still_enqueues_the_held_row(self) -> None:
        # A failed incremental run's staged tail is drained by the loader; a row left out of the queue
        # is a parquet file nothing ever loads.
        pipeline = self._staging_pipeline(["a", "b"])
        producer = pipeline._pg_producer

        def items():
            yield pa.table({"id": ["a"]})
            raise RuntimeError("source went away")

        pipeline._resource = SourceResponse(name="test_table", items=items, primary_keys=["id"])

        with pytest.raises(RuntimeError, match="source went away"):
            await self._run(pipeline)

        assert _queue_rows(producer) == [(0, False)]


def _passthrough_pool(fn):
    async def call(*args, **kwargs):
        return fn(*args, **kwargs)

    return call


class TestIncrementalHandoffCheckpoint:
    def _pipeline(self, items, events: list[Any], *, resumed_from: int | None = None) -> PipelineV3:
        pipeline = _make_pipeline()
        pipeline._pg_producer = _recording_producer(events)
        pipeline._batcher = Batcher(MagicMock(), primary_keys=["id"])
        pipeline._schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=True,
            is_webhook=False,
            is_append=False,
            should_use_incremental_field=True,
            incremental_field="n",
            incremental_field_type=IncrementalFieldType.Integer,
            table=None,
        )
        pipeline._schema.stage_handoff_resume_value.side_effect = lambda run_uuid, value, owner_run_uuid=None: (
            events.append(("resume_value", value))
        )
        pipeline._s3_batch_writer = MagicMock(
            write_batch=MagicMock(
                side_effect=lambda table, index: BatchWriteResult(
                    s3_path=f"s3://data/{index}.parquet",
                    row_count=table.num_rows,
                    byte_size=1,
                    batch_index=index,
                    timestamp_ns=0,
                )
            ),
            get_run_uuid=MagicMock(return_value="run-1"),
        )
        pipeline._resource = SourceResponse(name="test_table", items=items, primary_keys=["id"])
        pipeline._handoff_checkpoint = IncrementalHandoffCheckpoint(resumed_from)
        pipeline._staged_handoff_resume_value = resumed_from
        pipeline._batch_range_reader = IncrementalBatchRangeReader(pipeline._schema)

        async def stage_and_checkpoint(pa_table: pa.Table, batch_index: int, row_count: int) -> None:
            await pipeline._stage_batch(pa_table, batch_index, row_count)
            events.append(("staged_rows", pa_table.column("n").to_pylist()))
            await pipeline._advance_handoff_checkpoint(pa_table)

        pipeline._process_batch = AsyncMock(side_effect=stage_and_checkpoint)  # type: ignore[method-assign]
        return pipeline

    async def _run(self, pipeline: PipelineV3, exc: type[BaseException]) -> None:
        with ExitStack() as stack:
            for name in (
                "reset_rows_synced_if_needed",
                "setup_row_tracking_with_billing_check",
                "handle_reset_or_full_refresh",
                "handle_corrupted_delta_log",
            ):
                stack.enter_context(patch(f"{_PIPELINE}.{name}", new_callable=AsyncMock))
            for name in ("validate_incremental_sync", "record_source_item_stats"):
                stack.enter_context(patch(f"{_PIPELINE}.{name}"))
            stack.enter_context(patch(f"{_PIPELINE}.should_check_shutdown", return_value=True))
            stack.enter_context(patch(f"{_PIPELINE}.database_sync_to_async_pool", new=_passthrough_pool))
            stack.enter_context(patch(f"{_PRODUCER}.BatchQueue.supersede_other_runs", return_value=0))
            stack.enter_context(patch(f"{_PIPELINE}.activity")).in_activity.return_value = False
            with pytest.raises(exc):
                await pipeline.run()

    def _shut_down_at_check(self, pipeline: PipelineV3, check: int) -> None:
        monitor = cast(MagicMock, pipeline._shutdown_monitor)
        calls = {"n": 0}
        shutdown = WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")

        def is_shutdown() -> bool:
            calls["n"] += 1
            return calls["n"] >= check

        def raise_if_shutdown() -> None:
            if calls["n"] >= check:
                raise shutdown

        monitor.is_worker_shutdown.side_effect = is_shutdown
        monitor.raise_if_is_worker_shutdown.side_effect = raise_if_shutdown

    @pytest.mark.asyncio
    async def test_an_inherited_value_keeps_the_earlier_owner_until_this_attempt_queues_a_batch(self) -> None:
        # a2 inherits a1's value before extracting anything. If a2 hands off before queuing a batch
        # of its own, a3 must still finalize a1 - the run whose queue rows the value describes.
        events: list[Any] = []
        pipeline = self._pipeline(lambda: iter(()), events, resumed_from=40)
        pipeline._resumed_incremental_run_uuid = "run-0"

        stage_mock = cast(MagicMock, pipeline._schema.stage_handoff_resume_value)

        await pipeline._stage_handoff_resume_value(force=True)

        assert stage_mock.call_args.args == ("run-1", 40, "run-0")

        # Once a2 queues a batch of its own, it owns the queue rows: the owner is cleared so the
        # model defaults it to this run, even though the resume value itself has not changed yet.
        pipeline._queued_own_batch = True
        await pipeline._stage_handoff_resume_value()

        assert stage_mock.call_args.args == ("run-1", 40, None)

        # A later write from this attempt's own progress keeps the owner cleared.
        cast(IncrementalHandoffCheckpoint, pipeline._handoff_checkpoint)._resume_value = 55
        await pipeline._stage_handoff_resume_value()

        assert stage_mock.call_args.args == ("run-1", 55, None)

    @pytest.mark.asyncio
    async def test_ownership_follows_a_queue_row_only_once_it_is_actually_inserted(self) -> None:
        # The first batch an attempt holds is not inserted yet, so a crash right there must not grant
        # this attempt ownership of a queue row it does not yet have.
        pipeline = self._pipeline(lambda: iter(()), [], resumed_from=40)
        pipeline._resumed_incremental_run_uuid = "run-0"
        pipeline._pg_producer = _recording_producer(is_resume=True)

        await pipeline._stage_batch(pa.table({"id": ["a"], "n": [1]}), 0, 1)
        assert pipeline._queued_own_batch is False

        # Holding a second batch flushes the first one into the queue, so it is now this attempt's.
        await pipeline._stage_batch(pa.table({"id": ["b"], "n": [2]}), 1, 2)
        assert pipeline._queued_own_batch is True

    @pytest.mark.asyncio
    async def test_releasing_a_held_batch_also_grants_ownership(self) -> None:
        pipeline = self._pipeline(lambda: iter(()), [], resumed_from=40)
        pipeline._resumed_incremental_run_uuid = "run-0"
        pipeline._pg_producer = _recording_producer(is_resume=True)

        await pipeline._stage_batch(pa.table({"id": ["a"], "n": [1]}), 0, 1)
        assert pipeline._queued_own_batch is False

        pipeline._release_held_batches()

        assert pipeline._queued_own_batch is True

    @pytest.mark.asyncio
    async def test_a_handoff_stages_the_buffered_rows_and_then_records_where_to_continue(self) -> None:
        events: list[Any] = []

        def items():
            yield [{"id": 1, "n": 10}, {"id": 2, "n": 11}]
            yield [{"id": 3, "n": 12}]
            yield [{"id": 4, "n": 13}]

        pipeline = self._pipeline(items, events)
        self._shut_down_at_check(pipeline, check=2)

        await self._run(pipeline, WorkerShuttingDownError)

        # Neither item fills a chunk, so every row is still in the batcher at the shutdown check.
        # The queue row must exist before the value that tells the next attempt to skip its rows.
        assert events == [("staged_rows", [10, 11, 12]), "insert", ("resume_value", 11)]

    @pytest.mark.parametrize(
        "failure,expected_values",
        [
            # The source fails after three batches. The held row of the last batch is inserted on
            # the way out, so the next attempt can continue after all three.
            pytest.param("source_error", [10, 20, 29], id="every_batch_queued"),
            # The row of the last batch never reaches the queue, so its rows stay ahead of the value.
            pytest.param("held_row_not_inserted", [10, 20], id="held_batch_not_queued"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_recorded_value_never_passes_a_batch_without_a_queue_row(
        self, failure: str, expected_values: list[int]
    ) -> None:
        events: list[Any] = []

        def items():
            yield pa.table({"id": [1, 2], "n": [10, 11]})
            yield pa.table({"id": [3, 4], "n": [20, 21]})
            yield pa.table({"id": [5, 6], "n": [29, 30]})
            raise RuntimeError("source went away")

        pipeline = self._pipeline(items, events)
        cast(MagicMock, pipeline._shutdown_monitor).is_worker_shutdown.return_value = False
        if failure == "held_row_not_inserted":
            pipeline._pg_producer.release_held_batch = MagicMock(side_effect=RuntimeError("queue down"))  # type: ignore[method-assign]

        await self._run(pipeline, RuntimeError)

        assert [event[1] for event in events if event != "insert" and event[0] == "resume_value"] == expected_values

    @pytest.mark.asyncio
    async def test_a_queue_row_that_fails_to_insert_stops_the_value_from_advancing(self) -> None:
        events: list[Any] = []

        def items():
            yield pa.table({"id": [1, 2], "n": [10, 11]})
            yield pa.table({"id": [3, 4], "n": [20, 21]})
            yield pa.table({"id": [5, 6], "n": [29, 30]})

        pipeline = self._pipeline(items, events)
        cast(MagicMock, pipeline._shutdown_monitor).is_worker_shutdown.return_value = False
        inserts = {"n": 0}

        def fail_second_insert(*_args, **_kwargs) -> None:
            inserts["n"] += 1
            if inserts["n"] == 2:
                raise RuntimeError("queue down")

        cast(MagicMock, pipeline._pg_producer._conn.execute).side_effect = fail_second_insert

        await self._run(pipeline, RuntimeError)

        # Batch 1's row is the insert that failed. The value 10 covers batch 0 only, whose row exists.
        assert [event for event in events if event[0] == "resume_value"] == [("resume_value", 10)]

    @pytest.mark.asyncio
    async def test_rows_out_of_order_withdraw_the_recorded_value(self) -> None:
        events: list[Any] = []

        def items():
            yield pa.table({"id": [1, 2], "n": [10, 11]})
            yield pa.table({"id": [3, 4], "n": [20, 21]})
            yield pa.table({"id": [5, 6], "n": [5, 6]})
            raise RuntimeError("source went away")

        pipeline = self._pipeline(items, events)
        cast(MagicMock, pipeline._shutdown_monitor).is_worker_shutdown.return_value = False

        await self._run(pipeline, RuntimeError)

        assert [event[1] for event in events if event != "insert" and event[0] == "resume_value"] == [10, 20, None]

    @pytest.mark.parametrize(
        "resumed_incremental_value,expected_is_resume",
        [pytest.param(None, False, id="fresh_attempt"), pytest.param(40, True, id="continues_after_a_queued_batch")],
    )
    def test_an_attempt_that_continues_keeps_the_queue_rows_of_earlier_attempts(
        self, resumed_incremental_value: int | None, expected_is_resume: bool
    ) -> None:
        schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=True,
            is_webhook=False,
            is_xmin=False,
            is_append=False,
            table=None,
            incremental_field="n",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_field_earliest_value=None,
        )
        resource = SourceResponse(name="orders", items=lambda: iter(()), primary_keys=["id"])

        with (
            patch(f"{_PIPELINE}.current_import_attempt", return_value=2),
            patch(f"{_PIPELINE}.current_workflow_id", return_value="wf-1"),
            patch(f"{_PIPELINE}.current_workflow_run_id", return_value="wfrun-abc"),
            patch(f"{_PIPELINE}.S3BatchWriter"),
            patch(f"{_PIPELINE}.PostgresProducer") as producer_cls,
            patch(f"{_PIPELINE}.DeltaTableRef"),
            patch(f"{_PIPELINE}.resolve_primary_keys", return_value=["id"]),
        ):
            pipeline: PipelineV3 = PipelineV3(
                source_response=resource,
                logger=_make_logger(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                resumable_source_manager=None,
                models=ImportJobModels(
                    job=MagicMock(team_id=1, workflow_run_id="wfrun-abc", id="job-1", destination_ids=[]),
                    schema=schema,
                    source=MagicMock(source_type="Postgres"),
                    table=None,
                ),
                incremental_checkpoints_allowed=True,
                resumed_incremental_value=resumed_incremental_value,
            )

        # A fresh run replaces the queue rows of earlier attempts and overwrites on batch 0. A run that
        # reads after their rows must not, or the rows it skipped are never loaded.
        assert producer_cls.call_args.kwargs["is_resume"] is expected_is_resume
        assert pipeline._handoff_checkpoint is not None
        assert pipeline._handoff_checkpoint.resume_value == resumed_incremental_value


class _ShutdownSwitch:
    """Stands in for `ShutdownMonitor`. A source thread can start the shutdown at an exact point."""

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._flag = threading.Event()
        self.seen_by_event_loop = asyncio.Event()
        self._callbacks: list[Any] = []

    def shut_down(self) -> None:
        self._flag.set()
        self._loop.call_soon_threadsafe(self._notify)

    def _notify(self) -> None:
        for callback in self._callbacks:
            callback()
        self.seen_by_event_loop.set()

    def run_on_shutdown(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def is_worker_shutdown(self) -> bool:
        return self._flag.is_set()

    async def wait_for_worker_shutdown(self) -> None:
        await self.seen_by_event_loop.wait()

    def raise_if_is_worker_shutdown(self) -> None:
        if self._flag.is_set():
            raise WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")


def _dict_redis() -> MagicMock:
    store: dict[str, str] = {}
    redis = MagicMock()
    redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    redis.get.side_effect = store.get
    redis.exists.side_effect = lambda key: int(key in store)
    return redis


def _with_preemption(
    pipeline: PipelineV3, *, quiet_period_seconds: float = 0.0, carry_over: bool = True
) -> _ShutdownSwitch:
    switch = _ShutdownSwitch()
    pipeline._shutdown_monitor = cast(Any, switch)
    pipeline._shutdown_stopwatch = ShutdownStopwatch(cast(Any, switch))
    pipeline._preemption = PreemptionConfig(
        quiet_period_seconds=quiet_period_seconds, watermark_carry_over_enabled=carry_over
    )
    pipeline._source_resume_manager = pipeline._resumable_source_manager
    return switch


def _staged_ids(pipeline: PipelineV3) -> list[str]:
    return [
        row_id
        for call in cast(AsyncMock, pipeline._process_batch).await_args_list
        for row_id in call.kwargs["pa_table"].column("id").to_pylist()
    ]


class TestSourcePreemption:
    @pytest.mark.parametrize("late_write", ["commit", "clear_state"])
    @pytest.mark.asyncio
    async def test_a_source_blocked_in_a_call_is_handed_off_and_cannot_store_state_afterwards(
        self, late_write: str
    ) -> None:
        redis = MagicMock()
        manager = _manager()
        release = threading.Event()
        source_ended = threading.Event()
        seen: dict[str, Any] = {}

        def items():
            try:
                manager.save_state(_Cursor("a"))
                yield pa.table({"id": ["a"]})
                # Staged for a row that the blocked call has not returned yet.
                manager.save_state(_Cursor("b"))
                seen["daemon"] = threading.current_thread().daemon
                switch.shut_down()
                release.wait()
                try:
                    getattr(manager, late_write)()
                except BaseException as error:
                    seen["late_write_error"] = error
                    raise
            finally:
                source_ended.set()

        pipeline = _runnable_pipeline(manager, items)
        switch = _with_preemption(pipeline)

        try:
            await _run_expecting(pipeline, redis, SourcePreemptedError)
            committed_at_handoff = [json.loads(call.args[1])["id"] for call in redis.set.call_args_list]
        finally:
            release.set()
        with patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)):
            assert await asyncio.to_thread(source_ended.wait, 5)

        assert committed_at_handoff == ["a"]
        assert isinstance(seen["late_write_error"], SourceAbandonedError)
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == ["a"]
        redis.delete.assert_not_called()
        # A thread that never returns must not keep the worker process alive.
        assert seen["daemon"] is True

    @pytest.mark.asyncio
    async def test_a_source_that_reaches_a_safe_point_in_the_quiet_period_hands_off_with_its_cursor(self) -> None:
        redis = MagicMock()
        manager = _manager()

        def items():
            manager.save_state(_Cursor("a"))
            yield pa.table({"id": ["a"]})
            manager.save_state(_Cursor("b"))
            switch.shut_down()
            manager.safe_point()

        pipeline = _runnable_pipeline(manager, items)
        switch = _with_preemption(pipeline, quiet_period_seconds=3600.0)

        await _run_expecting(pipeline, redis, WorkerShuttingDownError)

        # A preemption leaves the staged cursor out, so the commit of `b` shows the usual hand-off.
        assert [json.loads(call.args[1])["id"] for call in redis.set.call_args_list] == ["a", "b"]

    @pytest.mark.parametrize(
        "preemption_on,resumable,expected_error",
        [
            # The source is the kind a preemption covers, so only the setting keeps the run waiting.
            pytest.param(False, True, WorkerShuttingDownError, id="setting_off"),
            pytest.param(True, False, RuntimeError, id="full_refresh_that_cannot_resume"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_pipeline_waits_for_the_source_when_it_must_not_preempt(
        self, preemption_on: bool, resumable: bool, expected_error: type[Exception]
    ) -> None:
        redis = MagicMock()
        manager = _manager()
        release = threading.Event()

        def items():
            yield pa.table({"id": ["a"]})
            switch.shut_down()
            release.wait()
            yield pa.table({"id": ["b"]})
            raise RuntimeError("end of the source")

        pipeline = _runnable_pipeline(manager, items)
        if not resumable:
            pipeline._resumable_source_manager = None
        switch = _with_preemption(pipeline)
        if not preemption_on:
            pipeline._preemption = None

        run = asyncio.ensure_future(_run_expecting(pipeline, redis, expected_error))
        try:
            await switch.seen_by_event_loop.wait()
            # A preemption needs no more than a few turns of the event loop from here.
            for _ in range(20):
                await asyncio.sleep(0)
            assert not run.done()
        finally:
            release.set()
        await run

        assert _staged_ids(pipeline) == ["a", "b"]
        if preemption_on:
            not_preempted = [
                call.kwargs["not_preempted_reason"]
                for call in cast(AsyncMock, pipeline._logger.ainfo).await_args_list
                if "not_preempted_reason" in call.kwargs
            ]
            assert not_preempted == ["non_resumable_full_refresh"]

    @pytest.mark.parametrize(
        "is_webhook,lanes,resumable,checkpoint,carry_over,young,expected",
        [
            pytest.param(False, False, True, None, False, False, (True, "resumable"), id="resumable"),
            pytest.param(False, False, False, "live", True, False, (True, "watermark_carry_over"), id="carry_over"),
            pytest.param(
                False, False, False, None, False, True, (True, "young_first_attempt"), id="young_first_attempt"
            ),
            pytest.param(
                False, False, False, "live", False, True, (True, "young_first_attempt"), id="young_without_carry_over"
            ),
            pytest.param(
                False,
                False,
                False,
                "live",
                False,
                False,
                (False, "watermark_carry_over_disabled"),
                id="carry_over_setting_off",
            ),
            # Rows arrived out of order, so the next attempt has no value to continue after.
            pytest.param(
                False, False, False, "void", True, False, (False, "no_watermark_carry_over"), id="void_checkpoint"
            ),
            pytest.param(
                False, False, False, None, True, False, (False, "non_resumable_full_refresh"), id="old_full_refresh"
            ),
            pytest.param(True, False, True, None, True, True, (False, "webhook"), id="webhook"),
            pytest.param(False, True, True, None, True, True, (False, "multiple_tables"), id="multiple_tables"),
        ],
    )
    def test_only_a_run_that_another_worker_can_continue_is_preempted(
        self,
        is_webhook: bool,
        lanes: bool,
        resumable: bool,
        checkpoint: str | None,
        carry_over: bool,
        young: bool,
        expected: tuple[bool, str],
    ) -> None:
        pipeline = _make_pipeline()
        pipeline._schema = MagicMock(is_webhook=is_webhook, should_use_incremental_field=checkpoint is not None)
        pipeline._resource = MagicMock(lanes=[MagicMock()] if lanes else None)
        pipeline._resumable_source_manager = MagicMock() if resumable else None
        pipeline._preemption = PreemptionConfig(quiet_period_seconds=60.0, watermark_carry_over_enabled=carry_over)
        if checkpoint is not None:
            pipeline._handoff_checkpoint = IncrementalHandoffCheckpoint()
            if checkpoint == "void":
                pipeline._handoff_checkpoint.observe(None)

        with patch(f"{_PIPELINE}.is_young_first_attempt", return_value=young):
            decision = pipeline._preemption_decision()

        assert (decision.eligible, decision.reason) == expected

    @pytest.mark.parametrize("rows_reach_a_batch", [True, False], ids=["rows_staged", "rows_still_buffered"])
    @pytest.mark.asyncio
    async def test_a_preempted_resumable_run_and_its_next_attempt_stage_every_row_once(
        self, rows_reach_a_batch: bool
    ) -> None:
        ids = ["a", "b", "c", "d", "e"]
        redis = _dict_redis()
        release = threading.Event()

        def source(manager: ResumableSourceManager[_Cursor], block_before: str | None, shut_down: Any):
            def items():
                state = manager.load_state()
                for row_id in ids[ids.index(state.id) + 1 if state else 0 :]:
                    # The cursor is staged before the read of its row, so it is ahead of the yielded
                    # rows for as long as that read takes.
                    manager.save_state(_Cursor(row_id))
                    if row_id == block_before:
                        shut_down()
                        release.wait()
                    yield pa.table({"id": [row_id]}) if rows_reach_a_batch else [{"id": row_id}]
                raise RuntimeError("end of the source")

            return items

        async def attempt(block_before: str | None, expected_error: type[Exception]) -> list[str]:
            manager = _manager()
            pipeline = _runnable_pipeline(manager, lambda: iter(()))
            switch = _with_preemption(pipeline)
            pipeline._resource = SourceResponse(
                name="test_table", items=source(manager, block_before, switch.shut_down), primary_keys=["id"]
            )
            await _run_expecting(pipeline, redis, expected_error)
            return _staged_ids(pipeline)

        try:
            interrupted = await attempt("c", SourcePreemptedError)
            continued = await attempt(None, RuntimeError)
            uninterrupted = ids
        finally:
            release.set()

        assert interrupted + continued == uninterrupted

    @pytest.mark.asyncio
    async def test_a_preempted_incremental_run_stages_its_buffered_rows_and_loses_none(self) -> None:
        events: list[Any] = []
        release = threading.Event()
        rows = [{"id": 1, "n": 10}, {"id": 2, "n": 11}, {"id": 3, "n": 12}, {"id": 4, "n": 13}]

        def items():
            yield rows[:2]
            yield rows[2:3]
            switch.shut_down()
            release.wait()
            yield rows[3:]

        checkpoint_tests = TestIncrementalHandoffCheckpoint()
        pipeline = checkpoint_tests._pipeline(items, events)
        switch = _with_preemption(pipeline)

        try:
            await checkpoint_tests._run(pipeline, SourcePreemptedError)
        finally:
            release.set()

        # The same order as a hand-off at an item: the queue row exists before the value that tells
        # the next attempt to skip its rows.
        assert events == [("staged_rows", [10, 11, 12]), "insert", ("resume_value", 11)]
        # The next attempt reads the source above the recorded value. Its rows and the staged rows
        # together are the rows of an uninterrupted run, and the loader merges the overlap by key.
        staged, resume_value = events[0][1], events[-1][1]
        next_attempt = [row["n"] for row in rows if row["n"] > resume_value]
        assert sorted(set(staged) | set(next_attempt)) == [row["n"] for row in rows]
