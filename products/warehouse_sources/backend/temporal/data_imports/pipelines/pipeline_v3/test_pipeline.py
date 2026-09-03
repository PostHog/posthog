from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.lanes import (
    LanedPipelineV3,
    _LaneWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportJobModels,
)


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

    pipeline._resource = MagicMock(
        name="test_table", primary_keys=["id"], lanes=None, finalize_metadata=None, on_nothing_staged=None
    )
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
            on_nothing_staged=None,
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
            on_nothing_staged=None,
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


def _run_uuids(lanes) -> list[str]:
    """Run ids the pipeline hands its S3 writers, one per lane."""
    mock_job = MagicMock(team_id=1, workflow_run_id="wfrun-abc", billable=False, id="job-1")
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
        cdc_write_mode=None,
        lanes=lanes,
        on_nothing_staged=None,
    )
    module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline"
    pipeline_cls: type[PipelineV3] = LanedPipelineV3 if lanes else PipelineV3
    with (
        patch(f"{module}.current_activity_attempt", return_value=3),
        patch(f"{module}.current_workflow_id", return_value="wf-1"),
        patch(f"{module}.current_workflow_run_id", return_value="wfrun-abc"),
        patch(f"{module}.S3BatchWriter") as mock_s3_writer_cls,
        patch(f"{module}.PostgresProducer"),
        patch(f"{module}.DeltaTableRef"),
    ):
        pipeline_cls(
            source_response=mock_resource,
            logger=_make_logger(),
            job_id="job-1",
            reset_pipeline=False,
            shutdown_monitor=MagicMock(),
            resumable_source_manager=None,
            models=ImportJobModels(job=mock_job, schema=mock_schema, source=mock_source_stub(), table=None),
        )
        return [call[0][3] for call in mock_s3_writer_cls.call_args_list]


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
        pipeline._resource.finalize_metadata = None
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


class TestLaneRunUuids:
    def test_a_single_lane_source_keeps_the_run_id_it_always_had(self) -> None:
        writers = _run_uuids(lanes=None)

        assert writers == ["wfrun-abc-a3"]

    def test_each_cdc_lane_gets_a_run_of_its_own(self) -> None:
        writers = _run_uuids(
            lanes=[
                OutputLane(name="users", cdc_write_mode="incremental_merge", run_uuid_suffix="-consolidated"),
                OutputLane(name="users_cdc", cdc_write_mode="scd2_append", run_uuid_suffix="-cdc"),
            ]
        )

        assert writers == ["wfrun-abc-a3-consolidated", "wfrun-abc-a3-cdc"]


@pytest.mark.asyncio
class TestSingleTableRunIsUntouched:
    """The base class is every non-lane source. Its staging path must not depend on lanes at all."""

    async def test_an_empty_batch_is_still_staged_and_counted(self) -> None:
        pipeline = _make_pipeline()
        pipeline._resource.finalize_metadata = None
        cast(MagicMock, pipeline._schema).configure_mock(incremental_field=None, enabled_columns=None)
        pipeline._last_incremental_field_value = None
        pipeline._earliest_incremental_field_value = None
        cast(MagicMock, pipeline._s3_batch_writer).write_batch = MagicMock(return_value=MagicMock(batch_index=0))

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
            await pipeline._process_batch(
                pa_table=pa.table({"id": pa.array([], pa.int64())}), batch_index=0, row_count=0
            )

        assert len(pipeline._batch_results) == 1
        cast(MagicMock, pipeline._pg_producer.send_batch_notification).assert_called_once()
        assert tracked.call_args[0][3] == 0

    def test_a_source_without_lanes_never_names_siblings(self) -> None:
        pipeline = _make_pipeline()
        pipeline._job.workflow_run_id = "wfrun-abc"
        pipeline._attempt = 1

        assert pipeline._sibling_run_uuids() == []
        assert pipeline._run_uuid_suffix() == ""


class TestLanedRunRequiresAWorkflowRunId:
    def test_a_laned_run_without_one_is_refused(self) -> None:
        # Lanes are told apart by a suffix on the workflow run id. Without one each lane falls back
        # to its writer's generated id, which no lane can name, so they would supersede each other's
        # batches and the first final batch would complete the job and delete the buffer.
        mock_job = MagicMock(team_id=1, workflow_run_id=None, billable=False, id="job-1")
        mock_schema = MagicMock(id="schema-1", source_id="source-1", table=None)
        mock_resource = MagicMock(
            primary_keys=["id"],
            lanes=[
                OutputLane(name="users", run_uuid_suffix="-consolidated"),
                OutputLane(name="users_cdc", run_uuid_suffix="-cdc"),
            ],
        )

        with pytest.raises(ValueError, match="no workflow_run_id"):
            LanedPipelineV3(
                source_response=mock_resource,
                logger=_make_logger(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                resumable_source_manager=None,
                models=ImportJobModels(job=mock_job, schema=mock_schema, source=MagicMock(), table=None),
            )


@pytest.mark.asyncio
class TestNothingStaged:
    async def test_a_run_that_stages_nothing_releases_what_it_read(self) -> None:
        # Every lane already held the whole read, so no final batch will carry the drained files.
        # AsyncMock, not MagicMock: the hook is awaited inside the pipeline's own event loop, and a
        # sync callable there raises "AsyncToSync in the same thread as an async event loop".
        released = AsyncMock()
        pipeline = _make_pipeline()
        pipeline._resource.on_nothing_staged = released
        pipeline._observed_columns = {}

        await pipeline._finalize(row_count=0)

        released.assert_awaited_once()

    async def test_a_run_that_staged_batches_does_not_release_them_early(self) -> None:
        released = AsyncMock()
        pipeline = _make_pipeline()
        pipeline._resource.on_nothing_staged = released
        pipeline._batch_results = [MagicMock(batch_index=0)]
        pipeline._observed_columns = {}
        pipeline._last_incremental_field_value = None
        pipeline._earliest_incremental_field_value = None
        cast(MagicMock, pipeline._s3_batch_writer).write_schema = MagicMock(return_value="s3://schema")
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

        released.assert_not_awaited()
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
