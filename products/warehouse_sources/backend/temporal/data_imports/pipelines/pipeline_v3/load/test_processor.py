from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    _apply_partitioning,
    _get_write_type,
    _promote_staged_cursor,
    process_message,
    process_messages,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.test_mocks import mock_delta_table


class TestGetWriteType:
    @parameterized.expand(
        [
            ("incremental", "incremental"),
            ("cdc", "incremental"),
            ("append", "append"),
            ("full_refresh", "full_refresh"),
        ]
    )
    def test_mapping(self, sync_type, expected):
        assert _get_write_type(sync_type) == expected


def _export_signal(**overrides: Any) -> MagicMock:
    signal = MagicMock()
    signal.partition_keys = overrides.get("partition_keys")
    signal.partition_count = overrides.get("partition_count")
    signal.partition_size = overrides.get("partition_size")
    signal.partition_mode = overrides.get("partition_mode")
    signal.partition_format = overrides.get("partition_format")
    return signal


def _schema(**overrides: Any) -> MagicMock:
    schema = MagicMock()
    schema.partitioning_enabled = overrides.get("partitioning_enabled", True)
    schema.partition_mode = overrides.get("partition_mode")
    schema.partition_format = overrides.get("partition_format")
    schema.partitioning_keys = overrides.get("partitioning_keys")
    schema.set_partitioning_enabled = MagicMock()
    return schema


_COL_ID = pa.field("id", pa.int64())
_COL_PARTITION = pa.field(PARTITION_KEY, pa.string())


class TestApplyPartitioning:
    """Regression coverage for the `DeltaError: Specified table partitioning does not match` bug.

    When a delta table contains `_ph_partition_key` in its schema but NOT in its
    partition columns (e.g. left over from a prior write committed with
    `partition_by=None`), the v3 loader must skip partitioning subsequent writes
    to avoid delta-rs rejecting the `partition_by=PARTITION_KEY` argument.
    """

    @parameterized.expand(
        [
            # Column in schema but NOT in partition_columns → skip (the exact bug scenario).
            ("column_in_schema_not_partitioned", [_COL_ID, _COL_PARTITION], [], False),
            # `metadata().partition_columns` returning None → skip defensively.
            ("partition_columns_is_none", [_COL_ID, _COL_PARTITION], None, False),
            # Truly partitioned by `_ph_partition_key` → happy path, partitioning applies.
            ("table_partitioned_by_key", [_COL_ID, _COL_PARTITION], [PARTITION_KEY], True),
        ]
    )
    def test_respects_existing_delta_partition_columns(
        self,
        _case: str,
        schema_fields: list[pa.Field],
        partition_columns: list[str] | None,
        expect_key: bool,
    ):
        pa_table = pa.table({"id": [1, 2, 3]})
        delta_table = mock_delta_table(schema_fields=schema_fields, partition_columns=partition_columns)

        schema_kwargs: dict[str, Any] = {}
        export_kwargs: dict[str, Any] = {"partition_keys": ["id"]}
        if expect_key:
            schema_kwargs.update(
                partitioning_enabled=True,
                partition_mode="md5",
                partitioning_keys=["id"],
            )
            export_kwargs["partition_count"] = 10

        result = _apply_partitioning(
            export_signal=_export_signal(**export_kwargs),
            pa_table=pa_table,
            existing_delta_table=delta_table,
            schema=_schema(**schema_kwargs),
        )

        if expect_key:
            assert PARTITION_KEY in result.column_names
        else:
            assert PARTITION_KEY not in result.column_names
            assert result.equals(pa_table)

    def test_skips_partitioning_when_no_partition_keys(self):
        pa_table = pa.table({"id": [1, 2, 3]})

        result = _apply_partitioning(
            export_signal=_export_signal(partition_keys=None),
            pa_table=pa_table,
            existing_delta_table=None,
            schema=_schema(),
        )

        assert PARTITION_KEY not in result.column_names
        assert result.equals(pa_table)


class TestPromoteStagedCursor:
    def _make_signal(self, **overrides: Any) -> MagicMock:
        signal = MagicMock()
        signal.schema_id = overrides.get("schema_id", "schema-1")
        signal.team_id = overrides.get("team_id", 1)
        signal.run_uuid = overrides.get("run_uuid", "run-abc-a1")
        signal.job_id = overrides.get("job_id", "job-1")
        return signal

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    def test_promotes_when_run_uuid_matches(self, mock_objects: MagicMock) -> None:
        schema = MagicMock()
        schema.promote_staged_incremental_values.return_value = True
        mock_objects.get.return_value = schema

        signal = self._make_signal()
        _promote_staged_cursor(signal)

        mock_objects.get.assert_called_once_with(id="schema-1", team_id=1)
        schema.promote_staged_incremental_values.assert_called_once_with("run-abc-a1")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    def test_does_not_raise_on_promotion_failure(self, mock_objects: MagicMock) -> None:
        schema = MagicMock()
        schema.promote_staged_incremental_values.side_effect = RuntimeError("db error")
        mock_objects.get.return_value = schema

        signal = self._make_signal()
        _promote_staged_cursor(signal)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    def test_does_not_raise_when_schema_missing(self, mock_objects: MagicMock) -> None:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        mock_objects.get.side_effect = ExternalDataSchema.DoesNotExist()
        signal = self._make_signal()
        _promote_staged_cursor(signal)


class _LeaseLost(Exception):
    pass


def _message(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "team_id": 1,
        "job_id": "job-1",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "resource_name": "res",
        "run_uuid": "run-1",
        "batch_index": 1,
        "s3_path": "s3://bucket/path",
        "row_count": 1,
        "byte_size": 1,
        "is_final_batch": False,
        "total_batches": None,
        "total_rows": None,
        "sync_type": "incremental",
        "data_folder": None,
        "schema_path": None,
        "primary_keys": ["id"],
    }
    base.update(overrides)
    return base


_PROCESSOR = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor"


class TestProcessMessageOwnershipGate:
    # If the check is dropped or moved after the side effect, a taken-over loader
    # would still commit to Delta or mark the job COMPLETED.

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_lost_ownership_blocks_delta_write(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=None)
        helper.write_to_deltalake = AsyncMock()
        helper.write_scd2_to_deltalake = AsyncMock()
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        def verify_ownership() -> None:
            raise _LeaseLost()

        with pytest.raises(_LeaseLost):
            process_message(_message(), verify_ownership=verify_ownership)

        helper.write_to_deltalake.assert_not_called()
        helper.write_scd2_to_deltalake.assert_not_called()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}._run_post_load_for_already_processed_batch")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_lost_ownership_blocks_final_batch_completion(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        _already: MagicMock,
        mock_post_load: MagicMock,
        mock_mark_completed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        def verify_ownership() -> None:
            raise _LeaseLost()

        with pytest.raises(_LeaseLost):
            process_message(_message(is_final_batch=True), verify_ownership=verify_ownership)

        mock_post_load.assert_not_called()
        mock_mark_completed.assert_not_called()


def _unit_message(batch_index: int, **overrides: Any) -> dict[str, Any]:
    return _message(batch_index=batch_index, s3_path=f"s3://bucket/batch-{batch_index}", **overrides)


def _mock_written_delta(schema: pa.Schema) -> MagicMock:
    delta = MagicMock()
    delta.schema = MagicMock(return_value=schema)
    delta.file_uris = MagicMock(return_value=[])
    delta.metadata = MagicMock(return_value=MagicMock(partition_columns=[]))
    return delta


class TestProcessMessagesCoalescing:
    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock)
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_unit_writes_once_in_index_order_and_completes_final(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        mock_post_load: AsyncMock,
        mock_mark_completed: MagicMock,
        mock_mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        schema = pa.schema([("id", pa.int64())])
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=None)
        helper.write_to_deltalake = AsyncMock(return_value=_mock_written_delta(schema))
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()
        mock_read.side_effect = lambda path: pa.table({"id": [int(path.rsplit("-", 1)[1])]})

        # Shuffled input: the processor must sort and concat in batch_index order,
        # or an older row would win the writer's keep-last dedupe (stale data).
        process_messages(
            [
                _unit_message(2),
                _unit_message(3, is_final_batch=True, total_rows=30),
                _unit_message(1),
            ]
        )

        helper.write_to_deltalake.assert_awaited_once()
        kwargs = helper.write_to_deltalake.await_args.kwargs
        assert kwargs["data"].column("id").to_pylist() == [1, 2, 3]
        # A redelivered mid-unit member is only detectable via the recorded range.
        assert kwargs["commit_metadata"] == {
            "run_uuid": "run-1",
            "batch_index": "3",
            "batch_index_start": "1",
            "batch_index_end": "3",
        }
        # Final-batch actions once per unit — never per member.
        mock_post_load.assert_awaited_once()
        mock_mark_completed.assert_called_once()
        assert mock_mark_processed.call_count == 3
        assert [call[0][3] for call in mock_mark_processed.call_args_list] == [1, 2, 3]

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}.evolve_pyarrow_schema", side_effect=lambda table, schema: table)
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_intra_unit_standalone_delete_enriched_from_earlier_member(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        _evolve: MagicMock,
        _mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_OP_COLUMN

        schema_fields: list[pa.Field] = [
            pa.field("id", pa.int64()),
            pa.field("name", pa.string()),
            pa.field(CDC_OP_COLUMN, pa.string()),
        ]
        schema = pa.schema(schema_fields)
        # Existing Delta state has no row for the PK — sequential per-batch merges
        # would still enrich the DELETE because batch 1's INSERT lands in Delta
        # before batch 2's merge reads it. The coalesced path must recover the
        # values from the earlier member of the unit instead.
        existing_delta = _mock_written_delta(schema)
        existing_delta.to_pyarrow_table = MagicMock(
            return_value=pa.table(
                {
                    "id": pa.array([], pa.int64()),
                    "name": pa.array([], pa.string()),
                    CDC_OP_COLUMN: pa.array([], pa.string()),
                }
            )
        )
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=existing_delta)
        helper.write_to_deltalake = AsyncMock(return_value=_mock_written_delta(schema))
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        batch_tables = {
            1: pa.table({"id": [1], "name": ["alice"], CDC_OP_COLUMN: ["I"]}),
            2: pa.table({"id": [1], "name": pa.array([None], pa.string()), CDC_OP_COLUMN: ["D"]}),
        }
        mock_read.side_effect = lambda path: batch_tables[int(path.rsplit("-", 1)[1])]

        process_messages(
            [
                _unit_message(1, sync_type="cdc", cdc_write_mode="consolidated"),
                _unit_message(2, sync_type="cdc", cdc_write_mode="consolidated"),
            ]
        )

        written = helper.write_to_deltalake.await_args.kwargs["data"]
        # A DELETE row written with null data columns would null the surviving
        # Delta row after the writer's keep-last dedupe.
        assert written.column("name").to_pylist() == ["alice", "alice"]
        assert written.column(CDC_OP_COLUMN).to_pylist() == ["I", "D"]

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}._run_post_load_for_already_processed_batch")
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_fully_processed_final_unit_completes_without_rewriting(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        mock_post_load: MagicMock,
        mock_mark_completed: MagicMock,
        _mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        # Crash-redelivery of a whole unit after its commit: the job must still
        # reach COMPLETED (post-load, cursor promotion, lock release) without
        # re-reading or re-writing any data.
        helper = mock_helper_cls.return_value
        helper.write_to_deltalake = AsyncMock()
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_messages([_unit_message(1), _unit_message(2, is_final_batch=True)])

        mock_read.assert_not_called()
        helper.write_to_deltalake.assert_not_called()
        mock_post_load.assert_called_once()
        assert mock_post_load.call_args[0][0].batch_index == 2
        mock_mark_completed.assert_called_once()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed")
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_already_processed_members_excluded_from_write(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_already: MagicMock,
        mock_read: MagicMock,
        mock_mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        schema = pa.schema([("id", pa.int64())])
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=None)
        helper.write_to_deltalake = AsyncMock(return_value=_mock_written_delta(schema))
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()
        mock_read.side_effect = lambda path: pa.table({"id": [int(path.rsplit("-", 1)[1])]})
        # Member 1 was committed before the crash; members 2-3 were not.
        mock_already.side_effect = lambda team_id, schema_id, run_uuid, batch_index, delta_table_helper=None: (
            batch_index == 1
        )

        process_messages([_unit_message(1), _unit_message(2), _unit_message(3)])

        kwargs = helper.write_to_deltalake.await_args.kwargs
        assert kwargs["data"].column("id").to_pylist() == [2, 3]
        # The commit range must only cover what this write actually merged.
        assert kwargs["commit_metadata"] == {
            "run_uuid": "run-1",
            "batch_index": "3",
            "batch_index_start": "2",
            "batch_index_end": "3",
        }
        assert mock_mark_processed.call_count == 3

    @parameterized.expand(
        [
            ("mixed_runs", [_unit_message(1), _unit_message(2, run_uuid="run-2")]),
            (
                "scd2_append",
                [
                    _unit_message(1, cdc_write_mode="scd2_append"),
                    _unit_message(2, cdc_write_mode="scd2_append"),
                ],
            ),
            (
                "first_ever_sync",
                [
                    _unit_message(0, is_first_ever_sync=True),
                    _unit_message(1, is_first_ever_sync=True),
                ],
            ),
        ]
    )
    def test_rejects_units_the_consumer_must_never_form(self, _case: str, messages: list[dict[str, Any]]) -> None:
        # Last line of defense: applying a cross-run, scd2, or first-ever-sync
        # unit as one write corrupts commit metadata, the scd2 valid_to chain,
        # or partial-data-loading semantics.
        with pytest.raises(ValueError):
            process_messages(messages)
