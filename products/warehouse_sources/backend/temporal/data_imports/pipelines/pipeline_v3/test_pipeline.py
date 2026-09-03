from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.lanes import (
    LanedPipelineV3,
    _LaneWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportJobModels,
)

_PIPELINE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline"
_LANES = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.lanes"
_CONSUMER = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer"


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
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_activity_attempt",
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
            patch(f"{base}.current_activity_attempt", return_value=1),
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
        patch(f"{_PIPELINE}.current_activity_attempt", return_value=3),
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
        base = _make_pipeline()
        pipeline = LanedPipelineV3.__new__(LanedPipelineV3)
        pipeline.__dict__.update(base.__dict__)
        pipeline._output_lanes = [writer.lane for writer in writers]
        pipeline._lane_writers = writers
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
            cast(MagicMock, writer.pg_producer.send_batch_notification).assert_called_once()

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
        cast(MagicMock, writers[1].pg_producer.send_batch_notification).assert_not_called()

    async def test_a_batch_that_arrives_empty_is_still_staged(self) -> None:
        # Every non-CDC source is one lane with no transform, and reaches here with an empty table
        # whenever its source yields one. Skipping it would move job completion from the load
        # consumer to the workflow for those syncs.
        writers = [_lane_writer("users")]
        pipeline = self._pipeline(writers)

        await self._process(pipeline, pa.table({"id": pa.array([], pa.int64())}))

        assert len(writers[0].batch_results) == 1

    async def test_each_lane_ends_with_its_own_final_batch(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", billable=False)]
        pipeline = self._pipeline(writers)
        await self._process(pipeline, pa.table({"id": pa.array([1], pa.int64())}))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.finalize_desc_sort_incremental_value",
                AsyncMock(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.advance_xmin_state",
                AsyncMock(),
            ),
        ):
            await pipeline._finalize(row_count=1)

        for writer in writers:
            call = cast(MagicMock, writer.pg_producer.send_batch_notification).call_args
            assert call.kwargs["is_final_batch"] is True

    async def test_a_lane_with_nothing_to_write_sends_no_final_batch(self) -> None:
        writers = [_lane_writer("users"), _lane_writer("users_cdc", transform=lambda t: t.slice(0, 0))]
        pipeline = self._pipeline(writers)
        await self._process(pipeline, pa.table({"id": pa.array([1], pa.int64())}))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.finalize_desc_sort_incremental_value",
                AsyncMock(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.advance_xmin_state",
                AsyncMock(),
            ),
        ):
            await pipeline._finalize(row_count=1)

        cast(MagicMock, writers[1].pg_producer.send_batch_notification).assert_not_called()


class TestCompanionJob:
    """A table beyond the first gets its own job, the way legacy CDC extraction writes `both`."""

    @staticmethod
    def _laned(lanes: list[OutputLane]) -> LanedPipelineV3:
        return _build_laned(lanes)

    @staticmethod
    def _open(pipeline: LanedPipelineV3, created: MagicMock) -> MagicMock:
        producer = MagicMock()
        with (
            patch(f"{_LANES}.PostgresProducer", producer),
            patch(
                f"{_LANES}.database_sync_to_async_pool", lambda fn: AsyncMock(side_effect=lambda *a, **k: fn(*a, **k))
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model._build_schema_snapshot",
                return_value={"name": "users"},
            ),
            patch("products.warehouse_sources.backend.models.external_data_job.ExternalDataJob.objects", created),
        ):
            async_to_sync(pipeline._open_companion_lanes)()
        return producer

    def test_a_single_lane_source_creates_no_companion(self) -> None:
        pipeline = self._laned([OutputLane(name="users_cdc", cdc_write_mode="scd2_append")])
        created = MagicMock()

        self._open(pipeline, created)

        created.create.assert_not_called()
        assert len(pipeline._lane_writers) == 1

    def test_the_companion_table_gets_its_own_job(self) -> None:
        pipeline = self._laned(
            [
                OutputLane(name="users", cdc_write_mode="incremental_merge"),
                OutputLane(name="users_cdc", cdc_write_mode="scd2_append"),
            ]
        )
        created = MagicMock()

        self._open(pipeline, created)

        fields = created.create.call_args.kwargs
        # No workflow run id: the schema's own job owns the pipeline lock, and a second holder
        # releasing it would free it while this run is still writing.
        assert fields["workflow_run_id"] is None
        # One read of a change stream is one sync however many tables it keeps.
        assert fields["billable"] is False
        assert fields["schema_snapshot"]["cdc_write_mode"] == "scd2_append"
        assert fields["schema_snapshot"]["companion_of"] == "job-1"

    def test_the_companion_writes_under_its_own_job_and_run(self) -> None:
        pipeline = self._laned(
            [
                OutputLane(name="users", cdc_write_mode="incremental_merge"),
                OutputLane(name="users_cdc", cdc_write_mode="scd2_append"),
            ]
        )
        created = MagicMock()
        created.create.return_value = MagicMock(id="companion-job")

        producer = self._open(pipeline, created)

        assert producer.call_args.kwargs["job_id"] == "companion-job"
        assert producer.call_args.kwargs["workflow_run_id"] is None
        companion = pipeline._lane_writers[1].job
        assert companion is not None and companion.id == "companion-job"

    def test_a_failed_run_takes_its_companion_job_terminal(self) -> None:
        # Nothing else would: the stranded sweep finds runs by their queued batches, so a
        # companion that failed before staging anything has none to be found by.
        pipeline = self._laned(
            [
                OutputLane(name="users", cdc_write_mode="incremental_merge"),
                OutputLane(name="users_cdc", cdc_write_mode="scd2_append"),
            ]
        )
        pipeline._lane_writers.append(
            _LaneWriter(
                lane=pipeline._output_lanes[1],
                s3_batch_writer=MagicMock(),
                pg_producer=MagicMock(),
                job=MagicMock(id="companion-job"),
            )
        )
        marked = MagicMock(return_value=True)

        with (
            patch(f"{_CONSUMER}.mark_job_failed_if_not_terminal", marked),
            patch(
                f"{_LANES}.database_sync_to_async_pool", lambda fn: AsyncMock(side_effect=lambda *a, **k: fn(*a, **k))
            ),
        ):
            async_to_sync(pipeline._fail_companion_jobs)()

        assert marked.call_args.kwargs["job_id"] == "companion-job"


@pytest.mark.asyncio
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
        pipeline._pg_producer.send_batch_notification.assert_called_once()

    def test_a_source_without_lanes_runs_the_base_class(self) -> None:
        assert _make_pipeline()._resource.lanes is None


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
    async def test_a_bookkeeping_failure_does_not_fail_the_sync(self) -> None:
        pipeline = _make_pipeline()
        pipeline._batch_results = []

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.update_sync_type_config_keys",
            new=MagicMock(side_effect=RuntimeError("pooler is down")),
        ):
            await pipeline._finalize(row_count=0)
