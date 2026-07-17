import tempfile
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    _apply_partitioning,
    _get_write_type,
    _mark_job_completed,
    _promote_staged_cursor,
    _read_existing_rows_by_first_pk,
    process_message,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.test_mocks import mock_delta_table


@pytest.fixture(autouse=True)
def _no_close_old_connections():
    # These are pure unit tests, but close_old_connections() touches the Django
    # connection, which pytest-django blocks for unmarked tests once a django_db
    # test has run in the same session — an order-dependent failure.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.close_old_connections"
    ):
        yield


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
    def test_promotion_failure_propagates(self, mock_objects: MagicMock) -> None:
        # If the failure is swallowed, the job completes with a stale cursor and
        # the next run re-extracts the same window — duplicate rows for append syncs.
        schema = MagicMock()
        schema.promote_staged_incremental_values.side_effect = RuntimeError("db error")
        mock_objects.get.return_value = schema

        signal = self._make_signal()
        with pytest.raises(RuntimeError):
            _promote_staged_cursor(signal)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    def test_missing_schema_propagates(self, mock_objects: MagicMock) -> None:
        # A deleted schema is permanent; the consumer's non-retryable patterns
        # fail the run fast instead of completing a job for a schema that's gone.
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        mock_objects.get.side_effect = ExternalDataSchema.DoesNotExist()
        signal = self._make_signal()
        with pytest.raises(ExternalDataSchema.DoesNotExist):
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

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}._run_post_load_for_already_processed_batch")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_ownership_lost_during_post_load_blocks_completion(
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
        # Post-load can run minutes; without the re-check a lease lost mid-post-load
        # still promotes the cursor and marks the job COMPLETED under a new owner.
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        calls = {"count": 0}

        def verify_ownership() -> None:
            calls["count"] += 1
            if calls["count"] > 1:
                raise _LeaseLost()

        with pytest.raises(_LeaseLost):
            process_message(_message(is_final_batch=True), verify_ownership=verify_ownership)

        mock_post_load.assert_called_once()
        mock_mark_completed.assert_not_called()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._run_post_load_for_already_processed_batch")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableHelper")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.s3fs")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_ownership_loss_is_not_counted_as_load_failure(
        self,
        _close: MagicMock,
        _s3fs: MagicMock,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        _already: MagicMock,
        _post_load: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        # Fencing abandons are benign; counting them as load failures pollutes the metric.
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
            OwnershipLostError,
        )

        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        def verify_ownership() -> None:
            raise OwnershipLostError("group lease lost")

        with pytest.raises(OwnershipLostError):
            process_message(_message(is_final_batch=True), verify_ownership=verify_ownership)

        mock_analytics.capture.assert_not_called()


class TestMarkJobCompleted:
    def _make_signal(self, **overrides: Any) -> MagicMock:
        signal = MagicMock()
        signal.schema_id = overrides.get("schema_id", "schema-1")
        signal.team_id = overrides.get("team_id", 1)
        signal.run_uuid = overrides.get("run_uuid", "run-abc-a1")
        signal.job_id = overrides.get("job_id", "job-1")
        return signal

    @parameterized.expand(
        [
            # If the job was cancelled (absorbing Failed) after the final batch passed
            # should_process_batch, the Completed write is rejected and the staged
            # incremental cursor must NOT be promoted.
            ("completed_write_lands", "Completed", True),
            ("completed_write_absorbed_by_failed", "Failed", False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.transaction")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.release_v3_pipeline_lock"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataJob.objects"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.finish_row_tracking",
        new_callable=AsyncMock,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.update_external_job_status"
    )
    def test_promotes_cursor_only_when_completed_write_lands(
        self,
        _case: str,
        resulting_status: str,
        expect_promotion: bool,
        mock_update: MagicMock,
        mock_schema_objects: MagicMock,
        mock_finish_row_tracking: AsyncMock,
        mock_job_objects: MagicMock,
        mock_release: MagicMock,
        mock_transaction: MagicMock,
    ) -> None:
        model = MagicMock()
        model.status = resulting_status
        mock_update.return_value = model

        schema = MagicMock()
        mock_schema_objects.get.return_value = schema
        job = MagicMock()
        job.workflow_run_id = "wf-run-1"
        mock_job_objects.only.return_value.get.return_value = job

        _mark_job_completed(self._make_signal())

        if expect_promotion:
            schema.promote_staged_incremental_values.assert_called_once_with("run-abc-a1")
        else:
            schema.promote_staged_incremental_values.assert_not_called()
            mock_finish_row_tracking.assert_not_awaited()
        # The pipeline lock must be released either way, or the next sync is blocked.
        mock_release.assert_called_once_with(team_id=1, schema_id="schema-1", token="wf-run-1")

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.transaction")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.release_v3_pipeline_lock"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.finish_row_tracking",
        new_callable=AsyncMock,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.update_external_job_status"
    )
    def test_promotion_failure_does_not_finalize_job(
        self,
        mock_update: MagicMock,
        mock_schema_objects: MagicMock,
        mock_finish_row_tracking: AsyncMock,
        mock_release: MagicMock,
        mock_transaction: MagicMock,
    ) -> None:
        # Promotion raising must propagate and skip finalization so the batch retries; otherwise the
        # job stays Completed with a stale cursor and a later append sync re-extracts the same window.
        model = MagicMock()
        model.status = "Completed"
        mock_update.return_value = model

        schema = MagicMock()
        schema.promote_staged_incremental_values.side_effect = RuntimeError("db error")
        mock_schema_objects.get.return_value = schema

        with pytest.raises(RuntimeError, match="db error"):
            _mark_job_completed(self._make_signal())

        mock_finish_row_tracking.assert_not_awaited()
        mock_release.assert_not_called()


# Regression guard for #70476: pyarrow 21+ string_view broke delta pushdown on string PKs.
class TestReadExistingRowsByFirstPk:
    @staticmethod
    def _string_view_table(path: str) -> DeltaTable:
        sv = pa.string_view()
        write_deltalake(
            path,
            pa.table({"id": pa.array(["a", "b", "c"], sv), "val": pa.array([1, 2, 3], pa.int64())}),
            mode="overwrite",
        )
        # Second file so file pruning is exercised.
        write_deltalake(
            path,
            pa.table({"id": pa.array(["d", "e", "f"], sv), "val": pa.array([4, 5, 6], pa.int64())}),
            mode="append",
        )
        return DeltaTable(path)

    @parameterized.expand(
        [
            ("subset_across_files", ["a", "e"], ["a", "e"]),
            ("single", ["c"], ["c"]),
            ("superset_with_miss", ["b", "zzz"], ["b"]),
            ("no_match", ["nope"], []),
        ]
    )
    def test_returns_matching_rows_on_string_view_pk(
        self, _name: str, components: list[str], expected_ids: list[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as path:
            delta_table = self._string_view_table(path)

            result = _read_existing_rows_by_first_pk(delta_table, "id", components)

            assert set(result.column("id").to_pylist()) == set(expected_ids)
