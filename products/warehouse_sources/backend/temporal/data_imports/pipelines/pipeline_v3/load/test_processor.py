import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
from asgiref.sync import async_to_sync
from deltalake import DeltaTable, write_deltalake
from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    SCD2_VALID_TO_COLUMN,
    TOAST_OMITTED_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import PostLoadResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    commit_covers_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    SUMMARY_EVENT,
    post_load_phase,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    INCOMPLETE_RUN_ERROR,
    IncompleteRunError,
    _apply_partitioning,
    _dedupe_before_write,
    _enrich_cdc_rows,
    _file_count_after_write,
    _get_write_type,
    _mark_job_completed,
    _promote_loaded_prefixes,
    _promote_staged_cursor,
    _read_existing_rows_by_first_pk,
    _rebuild_compaction_due,
    _resolve_cdc_positions,
    _run_post_load_for_already_processed_batch,
    _trigger_post_import_workflow,
    process_message,
    process_messages,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.table_handles import (
    GroupTableHandles,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.replace_scope import manifest_table
from products.warehouse_sources.backend.temporal.data_imports.pipelines.test_mocks import mock_delta_table
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.warehouse_sources_queue.backend.core.batch_consumer import CoalescingDeclined
from products.warehouse_sources_queue.backend.core.jobs_db import LoadedPrefix, UnfinishedEarlierBatches

_COMPLETE_RUN = UnfinishedEarlierBatches(count=0, first_batch_index=None, states=())


@pytest.fixture(autouse=True)
def _no_close_old_connections():
    # These are pure unit tests, but close_old_connections() touches the Django
    # connection, which pytest-django blocks for unmarked tests once a django_db
    # test has run in the same session — an order-dependent failure.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.close_old_connections"
    ):
        yield


@pytest.fixture(autouse=True)
def _unfinished_earlier_batches() -> Iterator[MagicMock]:
    # The completion check reads the queue DB, which these unit tests do not have.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.BatchQueue.get_unfinished_earlier_batches_sync",
        return_value=_COMPLETE_RUN,
    ) as check:
        yield check


@pytest.fixture(autouse=True)
def _table_handles() -> Iterator[GroupTableHandles]:
    # The loader's registry is process-wide, so a handle that one test left would reach the next.
    handles = GroupTableHandles()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.GROUP_TABLE_HANDLES",
        handles,
    ):
        yield handles


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


_COL_ID: pa.Field[pa.DataType] = pa.field("id", pa.int64())
_COL_PARTITION: pa.Field[pa.DataType] = pa.field(PARTITION_KEY, pa.string())


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
        schema.promote_staged_incremental_values.assert_called_once_with("run-abc-a1", merge_source_cursors=ANY)

    @parameterized.expand(
        [
            ("incremental_run_warns", True, 1),
            ("full_refresh_run_stays_quiet", False, 0),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.logger")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.ExternalDataSchema.objects"
    )
    def test_warns_when_a_completed_run_has_no_staged_cursor(
        self, _name: str, uses_incremental_field: bool, warnings: int, mock_objects: MagicMock, mock_logger: MagicMock
    ) -> None:
        schema = MagicMock()
        schema.promote_staged_incremental_values.return_value = False
        schema.should_use_incremental_field = uses_incremental_field
        mock_objects.get.return_value = schema

        _promote_staged_cursor(self._make_signal())

        assert mock_logger.warning.call_count == warnings
        if warnings:
            assert mock_logger.warning.call_args.args == ("staged_cursor_missing",)

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
_REPLACE_ROWS = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.replace_rows"
_REPLACE_SCOPE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.replace_scope"
_IDEMPOTENCY = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.idempotency"
_POST_LOAD_RESULT = PostLoadResult(queryable_folder="folder", table_size_written=True)


class TestProcessMessageOwnershipGate:
    # If the check is dropped or moved after the side effect, a taken-over loader
    # would still commit to Delta or mark the job COMPLETED.

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.Scd2DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_lost_ownership_blocks_delta_write(
        self,
        _close: MagicMock,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_scd2_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=None)
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        def verify_ownership() -> None:
            raise _LeaseLost()

        with pytest.raises(_LeaseLost):
            process_message(_message(), verify_ownership=verify_ownership)

        mock_writer_cls.return_value.write.assert_not_called()
        mock_scd2_cls.return_value.write.assert_not_called()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}._run_post_load_for_already_processed_batch")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_lost_ownership_blocks_final_batch_completion(
        self,
        _close: MagicMock,
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
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_ownership_lost_during_post_load_blocks_completion(
        self,
        _close: MagicMock,
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
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_ownership_loss_is_not_counted_as_load_failure(
        self,
        _close: MagicMock,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        _already: MagicMock,
        _post_load: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        # Fencing abandons are benign; counting them as load failures pollutes the metric.
        from products.warehouse_sources_queue.backend.core.batch_consumer import OwnershipLostError

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
            schema.promote_staged_incremental_values.assert_called_once_with("run-abc-a1", merge_source_cursors=ANY)
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

    @parameterized.expand(
        [
            (
                "aged_out_batch_never_loaded",
                UnfinishedEarlierBatches(count=1, first_batch_index=2, states=("pending",)),
            ),
            ("earlier_batch_failed", UnfinishedEarlierBatches(count=1, first_batch_index=0, states=("failed",))),
            (
                "several_batches_left",
                UnfinishedEarlierBatches(count=3, first_batch_index=1, states=("pending", "waiting_retry")),
            ),
        ]
    )
    @patch(f"{_PROCESSOR}.release_v3_pipeline_lock")
    @patch(f"{_PROCESSOR}.ExternalDataSchema.objects")
    @patch(f"{_PROCESSOR}.update_external_job_status")
    def test_a_run_with_an_unfinished_earlier_batch_does_not_complete(
        self,
        _case: str,
        unfinished: UnfinishedEarlierBatches,
        mock_update: MagicMock,
        mock_schema_objects: MagicMock,
        mock_release: MagicMock,
    ) -> None:
        signal = self._make_signal()
        signal.batch_index = 5

        with (
            patch(f"{_PROCESSOR}.BatchQueue.get_unfinished_earlier_batches_sync", return_value=unfinished) as check,
            pytest.raises(IncompleteRunError, match=INCOMPLETE_RUN_ERROR),
        ):
            _mark_job_completed(signal)

        assert check.call_args.kwargs == {
            "team_id": 1,
            "schema_id": "schema-1",
            "run_uuid": "run-abc-a1",
            "before_batch_index": 5,
        }
        mock_update.assert_not_called()
        mock_schema_objects.get.return_value.promote_staged_incremental_values.assert_not_called()
        # The consumer fails the run on this error, and its fail path releases the lock.
        mock_release.assert_not_called()


class TestRedeliveredFinalBatchPostLoad:
    @parameterized.expand([("companion", "scd2_append"), ("consolidated", "incremental_merge"), ("snapshot", None)])
    @patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, return_value=_POST_LOAD_RESULT)
    @patch(f"{_PROCESSOR}.read_parquet_first_values", return_value=pa.table({"id": [1], "payload": ['{"a": 1}']}))
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_forwards_the_batch_write_mode(
        self,
        _case: str,
        cdc_write_mode: str | None,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        _read: MagicMock,
        mock_post_load: AsyncMock,
    ) -> None:
        # Post-load derives the whole CDC branch from the write mode: whether this is a companion
        # write (register the _cdc table, leave schema.table alone) or a snapshot to seed the
        # companion from. Dropping it here let a redelivered streaming batch re-seed the companion,
        # wiping its SCD2 history, and point schema.table at the companion's folder.
        delta_table = MagicMock(schema=MagicMock(return_value=pa.schema([_COL_ID, pa.field("payload", pa.string())])))
        mock_job_model.objects.prefetch_related.return_value.aget = AsyncMock(return_value=MagicMock())
        mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=delta_table)

        signal = MagicMock()
        signal.cdc_write_mode = cdc_write_mode

        _run_post_load_for_already_processed_batch(signal)

        assert mock_post_load.await_args is not None
        assert mock_post_load.await_args.kwargs["cdc_write_mode"] == cdc_write_mode
        # The table schema alone types the column as a plain string; the batch's first value says JSON.
        assert mock_post_load.await_args.kwargs["table_schema_dict"] == {
            "id": "IntegerDatabaseField",
            "payload": "StringJSONDatabaseField",
        }


class TestPostWriteHandleReads:
    # `DeltaWriter.write` can return a handle one deltalite commit behind the log. Column names and
    # types survive that lag, a file list does not: partial data loading must read its file list
    # through the ref, which catches the handle up, and a plain batch must not pay that read.

    @parameterized.expand(
        [
            ("plain_batch", 1, False, 1, 1, 1, None),
            ("partial_data_loading", 1, True, 1, 1, 2, None),
            # Batch 0 is a file-count sample and is the only batch of most runs.
            ("sampled_batch_after_a_deltalite_commit", 0, False, 1, 1, 1, 3),
            ("sampled_batch_on_a_current_handle", 0, False, 0, None, 1, 2),
            ("sampled_batch_behind_by_a_foreign_commit", 0, False, 2, 1, 2, 5),
            ("sampled_batch_with_no_commit_stats", 0, False, 1, None, 2, 5),
        ]
    )
    @patch(f"{_PROCESSOR}.logger")
    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._handle_partial_data_loading", new_callable=AsyncMock)
    @patch(f"{_PROCESSOR}.supports_partial_data_loading", return_value=True)
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_file_list_readers_go_through_the_ref(
        self,
        _case: str,
        batch_index: int,
        is_first_ever_sync: bool,
        commits_behind: int,
        deltalite_file_count_change: int | None,
        expected_handle_reads: int,
        expected_file_count: int | None,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _supports: MagicMock,
        mock_partial: AsyncMock,
        _mark: MagicMock,
        _analytics: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        returned = MagicMock()
        returned.schema.return_value = pa.schema([_COL_ID])
        returned.version.return_value = 7
        returned.file_uris.return_value = ["a", "b"]
        current = MagicMock()
        current.schema.return_value = pa.schema([_COL_ID])
        current.file_uris.return_value = ["a", "b", "c", "d", "e"]
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=current)
        helper.latest_known_version.return_value = 7 + commits_behind
        mock_writer_cls.return_value.write = AsyncMock(return_value=returned)
        mock_writer_cls.return_value.deltalite_file_count_change = deltalite_file_count_change
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_message(_message(batch_index=batch_index, is_first_ever_sync=is_first_ever_sync))

        # One read opens the table before the write; only a file-list reader adds a second.
        assert helper.get_delta_table.await_count == expected_handle_reads
        assert mock_partial.await_args is not None
        assert mock_partial.await_args.kwargs["delta_table"] is (current if expected_handle_reads == 2 else returned)
        written = [call for call in mock_logger.debug.call_args_list if call.args[0] == "batch_written_to_delta_lake"]
        assert len(written) == 1
        assert written[0].kwargs["file_count"] == expected_file_count


class TestFileCountAfterWrite:
    def test_the_count_from_memory_is_the_count_in_the_log(self, tmp_path: Path) -> None:
        # The sampled file count comes from the handle `write` returns plus the commit's own numbers,
        # with no read of the log. If the handle's lag or the upsert stats stop meaning what the
        # arithmetic assumes, the log line goes wrong without an error.
        path = str(tmp_path / "table")
        seed = pa.table({"id": pa.array([1, 2, 101], pa.int64()), PARTITION_KEY: ["a", "a", "b"], "v": ["x", "y", "z"]})
        write_deltalake(path, seed, partition_by=PARTITION_KEY)
        ref = make_local_table_ref(path)
        writer = DeltaWriter(ref)
        handle_lags: set[int] = set()

        writes: list[tuple[list[int], list[str], Any, list[str] | None]] = [
            ([1], ["a"], "incremental", ["id"]),
            ([500], ["c"], "incremental", ["id"]),
            ([1, 101, 500, 900], ["a", "b", "c", "d"], "incremental", ["id"]),
            ([7], ["a"], "append", None),
        ]
        for ids, partitions, write_type, primary_keys in writes:
            batch = pa.table({"id": pa.array(ids, pa.int64()), PARTITION_KEY: partitions, "v": ["new"] * len(ids)})
            returned = async_to_sync(writer.write)(
                data=batch, write_type=write_type, should_overwrite_table=False, primary_keys=primary_keys
            )
            handle_lags.add(ref.latest_known_version(returned) - returned.version())

            file_count = _file_count_after_write(returned, ref, writer.deltalite_file_count_change)

            assert file_count == len(DeltaTable(path).file_uris())

        # Both a current handle and one that a deltalite commit left behind were read.
        assert handle_lags == {0, 1}


class TestFinalDataBatch:
    # The run's last data row is its own final marker, so one delivery writes the batch and runs
    # post-load. The write must be marked as soon as it commits: a post-load failure otherwise
    # leaves the retry with no fast way to know the merge already happened.

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(
        f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, side_effect=RuntimeError("compaction died")
    )
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_a_post_load_failure_leaves_the_write_marked_processed(
        self,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _post_load: AsyncMock,
        mock_mark_completed: MagicMock,
        mock_mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=None)
        mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="compaction died"):
            process_message(_message(is_final_batch=True, batch_index=4, run_uuid="run-9"))

        mock_writer_cls.return_value.write.assert_awaited_once()
        mock_mark_processed.assert_called_once_with(1, "schema-1", "run-9", 4)
        mock_mark_completed.assert_not_called()


class TestStagedCursorWaitsForTheFinalBatch:
    # A descending source stages the newest value of its run from the first batch. Promoting it on a
    # batch before the final one moves the watermark above rows that are not loaded yet.

    @parameterized.expand([("mid_run_batch", False, 0, 1), ("final_batch", True, 1, 0)])
    @override_settings(DATA_WAREHOUSE_IMPORT_PREFIX_WATERMARK_ENABLED=True)
    def test_a_staged_cursor_is_promoted_only_by_the_final_batch(
        self, _name: str, is_final_batch: bool, promotions: int, prefix_promotions: int
    ) -> None:
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        with ExitStack() as stack:
            for target in (
                "posthoganalytics",
                "mark_batch_as_processed",
                "_trigger_post_import_workflow",
                "_trigger_ducklake_register_data_imports",
                "transaction",
                "release_v3_pipeline_lock",
            ):
                stack.enter_context(patch(f"{_PROCESSOR}.{target}"))
            stack.enter_context(patch(f"{_PROCESSOR}.finish_row_tracking", new_callable=AsyncMock))
            stack.enter_context(
                patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, return_value=_POST_LOAD_RESULT)
            )
            stack.enter_context(patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]})))
            stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            mock_writer_cls = stack.enter_context(patch(f"{_PROCESSOR}.DeltaWriter"))
            mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)
            mock_helper_cls = stack.enter_context(patch(f"{_PROCESSOR}.DeltaTableRef"))
            mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=None)
            mock_job_cls = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            mock_update = stack.enter_context(patch(f"{_PROCESSOR}.update_external_job_status"))
            mock_update.return_value.status = mock_job_cls.Status.COMPLETED
            mock_schema_objects = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataSchema.objects"))
            stack.enter_context(
                patch(
                    f"{_PROCESSOR}.BatchQueue.get_loaded_prefix_sync",
                    return_value=LoadedPrefix(is_complete=True, cursor=_PREFIX_CURSOR),
                )
            )

            process_message(_message(is_final_batch=is_final_batch, run_uuid="wfrun-1-a2"))

        promote = mock_schema_objects.get.return_value.promote_staged_incremental_values
        assert promote.call_count == promotions
        if promotions:
            promote.assert_called_with("wfrun-1-a2", merge_source_cursors=ANY)
        # The final batch promotes the full staged value, so only a batch before it promotes a prefix.
        promote_prefix = mock_job_cls.objects.prefetch_related.return_value.get.return_value.schema
        assert promote_prefix.promote_loaded_prefix_value.call_count == prefix_promotions


_PREFIX_CURSOR = {"field": "id", "value": 30, "job_rows_synced": 7}


class _PromoteMocks(NamedTuple):
    get_prefix: MagicMock
    promote: MagicMock


class TestPromoteLoadedPrefixes:
    @staticmethod
    def _signals(*indexes: int, **overrides: Any) -> list[ExportSignalMessage]:
        return [ExportSignalMessage.from_dict(_message(batch_index=index, **overrides)) for index in indexes]

    @staticmethod
    def _promote(
        signals: list[ExportSignalMessage],
        prefix: LoadedPrefix | Exception,
        *,
        finals: list[ExportSignalMessage] | None = None,
        enabled: bool = True,
    ) -> _PromoteMocks:
        schema = MagicMock()
        with (
            override_settings(DATA_WAREHOUSE_IMPORT_PREFIX_WATERMARK_ENABLED=enabled),
            patch(f"{_PROCESSOR}.BatchQueue.get_loaded_prefix_sync", side_effect=[prefix]) as get_prefix,
            patch(f"{_PROCESSOR}.capture_exception"),
        ):
            _promote_loaded_prefixes(signals, finals or [], schema)
        return _PromoteMocks(get_prefix=get_prefix, promote=schema.promote_loaded_prefix_value)

    def test_a_loaded_prefix_promotes_the_value_of_the_last_batch_of_the_write(self) -> None:
        get_prefix, promote = self._promote(
            self._signals(3, 4, 5), LoadedPrefix(is_complete=True, cursor=_PREFIX_CURSOR)
        )

        assert get_prefix.call_args.kwargs == {
            "team_id": 1,
            "schema_id": "schema-1",
            "run_uuid": "run-1",
            "first_batch_index": 3,
            "last_batch_index": 5,
        }
        promote.assert_called_once_with(run_uuid="run-1", job_id="job-1", field="id", value=30, job_rows_synced=7)

    @parameterized.expand(
        [
            # An earlier batch is missing, aged out, failed or waits for a retry.
            ("gap_before_the_write", LoadedPrefix(is_complete=False, cursor=_PREFIX_CURSOR)),
            # A pod without the setting, or a run that cannot promote, queued the batch.
            ("batch_has_no_cursor", LoadedPrefix(is_complete=True, cursor=None)),
            ("cursor_in_an_unknown_shape", LoadedPrefix(is_complete=True, cursor={"value": 30})),
            # A queue read that fails must not fail a batch that already landed.
            ("queue_read_fails", RuntimeError("queue down")),
        ]
    )
    def test_no_promotion(self, _name: str, prefix: LoadedPrefix | Exception) -> None:
        _get_prefix, promote = self._promote(self._signals(2), prefix)

        promote.assert_not_called()

    @parameterized.expand(
        [
            ("setting_off", {}, False, False),
            ("final_batch_promotes_the_full_value", {}, True, True),
            ("append", {"sync_type": "append"}, False, True),
            ("full_refresh", {"sync_type": "full_refresh"}, False, True),
            ("cdc", {"cdc_write_mode": "scd2_append"}, False, True),
            ("first_ever_sync", {"is_first_ever_sync": True}, False, True),
        ]
    )
    def test_a_write_that_cannot_promote_a_prefix_reads_nothing(
        self, _name: str, overrides: dict[str, Any], completes_here: bool, enabled: bool
    ) -> None:
        signals = self._signals(2, **overrides)

        get_prefix, promote = self._promote(
            signals,
            LoadedPrefix(is_complete=True, cursor=_PREFIX_CURSOR),
            finals=signals if completes_here else None,
            enabled=enabled,
        )

        get_prefix.assert_not_called()
        promote.assert_not_called()


def _set_messages(count: int, *, sync_type: str = "full_refresh", final: bool = True) -> list[dict[str, Any]]:
    return [
        _message(
            batch_index=index,
            s3_path=f"s3://bucket/{index}.parquet",
            sync_type=sync_type,
            is_final_batch=final and index == count - 1,
            total_batches=count if final and index == count - 1 else None,
            total_rows=6 if final and index == count - 1 else None,
            row_count=index + 1,
        )
        for index in range(count)
    ]


class TestProcessMessages:
    """Several consecutive batches of one run loaded as one write. The write must carry every member,
    or a redelivery of one of them merges its rows a second time."""

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}._trigger_ducklake_register_data_imports")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, return_value=_POST_LOAD_RESULT)
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_a_set_starting_at_batch_zero_overwrites_with_the_union_and_finishes_the_run(
        self,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        mock_post_load: AsyncMock,
        mock_mark_completed: MagicMock,
        _ducklake: MagicMock,
        mock_trigger: MagicMock,
        mock_mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        mock_read.side_effect = lambda path: pa.table({"id": list(range(int(path[-9]) + 1))})
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=None)
        mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_messages(_set_messages(3))

        write = mock_writer_cls.return_value.write
        write.assert_awaited_once()
        assert write.await_args.kwargs["data"].num_rows == 6
        assert write.await_args.kwargs["should_overwrite_table"] is True
        assert write.await_args.kwargs["commit_metadata"] == {
            "run_uuid": "run-1",
            "batch_index": "0",
            "batch_indexes": "0,1,2",
        }
        assert [call.args[3] for call in mock_mark_processed.call_args_list] == [0, 1, 2]
        mock_post_load.assert_awaited_once()
        assert mock_post_load.await_args is not None
        assert mock_post_load.await_args.kwargs["row_count"] == 6
        mock_mark_completed.assert_called_once()
        # Without the flag the post-import workflow opens the table again to measure a size that
        # post-load already recorded.
        mock_trigger.assert_called_once_with(ANY, True)
        # The completion check counts the batches below this index as earlier writes. The tail index
        # would count the set's own members, which are still executing, and fail every coalesced run.
        assert mock_mark_completed.call_args.args[0].batch_index == 0

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", side_effect=[False, True, False])
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_a_member_that_already_landed_declines_the_set_before_any_read_or_write(
        self,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        with pytest.raises(CoalescingDeclined):
            process_messages(_set_messages(3))

        mock_read.assert_not_called()
        mock_writer_cls.return_value.write.assert_not_called()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.read_parquet")
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_members_whose_schemas_do_not_concatenate_decline_the_set(
        self,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        mock_read: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        mock_read.side_effect = [pa.table({"id": [1]}), pa.table({"id": ["a"]})]
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        with pytest.raises(CoalescingDeclined):
            process_messages(_set_messages(2))

        mock_writer_cls.return_value.write.assert_not_called()

    @parameterized.expand(
        [
            ("gap_in_indexes", [{"batch_index": 0}, {"batch_index": 2}]),
            ("fresh_run_batch_zero", [{"batch_index": 3}, {"batch_index": 0, "run_uuid": "run-2"}]),
            (
                "full_refresh_across_runs",
                [
                    {"batch_index": 3, "sync_type": "full_refresh"},
                    {"batch_index": 0, "run_uuid": "run-2", "is_resume": True, "sync_type": "full_refresh"},
                ],
            ),
            (
                "other_primary_keys",
                [{"batch_index": 3}, {"batch_index": 0, "run_uuid": "run-2", "is_resume": True, "primary_keys": ["k"]}],
            ),
            (
                "run_reappears",
                [{"batch_index": 3}, {"batch_index": 0, "run_uuid": "run-2", "is_resume": True}, {"batch_index": 4}],
            ),
            ("cdc", [{"batch_index": 0, "sync_type": "cdc"}, {"batch_index": 1, "sync_type": "cdc"}]),
        ]
    )
    def test_a_set_the_rules_reject_is_declined_before_any_side_effect(
        self, _case: str, overrides: list[dict[str, Any]]
    ) -> None:
        # The consumer never builds these, so reaching here means a planner bug; the sink must
        # refuse rather than merge rows the serial loader would have written differently.
        with pytest.raises(CoalescingDeclined):
            process_messages([_message(**o) for o in overrides])

    @parameterized.expand(
        [
            # Both runs end in the set: each completes, in load order, with its own job and totals.
            ("both_runs_final", True, ["run-1", "run-2"], ["job-1", "job-2"]),
            # The second run continues past the set: only the first run completes.
            ("second_run_open", False, ["run-1"], ["job-1"]),
        ]
    )
    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}._trigger_ducklake_register_data_imports")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, return_value=_POST_LOAD_RESULT)
    @patch(
        f"{_PROCESSOR}.read_parquet",
        side_effect=lambda path: pa.table({"id": [int(path.rsplit("/", 1)[1].removesuffix(".parquet"))]}),
    )
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_a_set_spanning_runs_keeps_every_member_and_every_run_apart(
        self,
        _case: str,
        second_run_final: bool,
        completed_runs: list[str],
        completed_jobs: list[str],
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        mock_already: MagicMock,
        _read: MagicMock,
        mock_post_load: AsyncMock,
        mock_mark_completed: MagicMock,
        _ducklake: MagicMock,
        mock_trigger: MagicMock,
        mock_mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        jobs = {job_id: MagicMock(name=job_id) for job_id in ("job-1", "job-2")}
        mock_job_model.objects.prefetch_related.return_value.get.side_effect = lambda id: jobs[id]
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=None)
        mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)

        messages = _run_messages("run-1", start=3, count=2, final=True) + _run_messages(
            "run-2", start=0, count=2, final=second_run_final, is_resume=True
        )
        process_messages(messages)

        members = [("run-1", 3), ("run-1", 4), ("run-2", 0), ("run-2", 1)]
        assert [(call.args[2], call.args[3]) for call in mock_already.call_args_list] == members
        assert [(call.args[2], call.args[3]) for call in mock_mark_processed.call_args_list] == members
        write = mock_writer_cls.return_value.write
        write.assert_awaited_once()
        assert write.await_args.kwargs["data"].num_rows == 4
        assert write.await_args.kwargs["should_overwrite_table"] is False
        assert write.await_args.kwargs["commit_metadata"] == {
            "run_uuid": "run-1",
            "batch_index": "3",
            "batch_indexes": "3,4",
            "members": "run-1:3,run-1:4,run-2:0,run-2:1",
        }
        assert [call.kwargs["job"] for call in mock_post_load.await_args_list] == [jobs[j] for j in completed_jobs]
        assert [call.kwargs["row_count"] for call in mock_post_load.await_args_list] == [
            _run_total_rows(run) for run in completed_runs
        ]
        assert [call.args[0].run_uuid for call in mock_mark_completed.call_args_list] == completed_runs
        assert [call.args[0].job_id for call in mock_mark_completed.call_args_list] == completed_jobs
        assert [call.args[0].run_uuid for call in mock_trigger.call_args_list] == completed_runs


def _run_total_rows(run_uuid: str) -> int:
    return 1000 + int(run_uuid[-1])


def _run_messages(
    run_uuid: str, *, start: int, count: int, final: bool, is_resume: bool = False, **overrides: Any
) -> list[dict[str, Any]]:
    return [
        _message(
            **{
                "run_uuid": run_uuid,
                "job_id": f"job-{run_uuid[-1]}",
                "batch_index": start + offset,
                "s3_path": f"s3://bucket/{run_uuid}/{start + offset}.parquet",
                "is_resume": is_resume,
                "is_final_batch": final and offset == count - 1,
                "total_batches": start + count if final and offset == count - 1 else None,
                "total_rows": _run_total_rows(run_uuid) if final and offset == count - 1 else None,
                **overrides,
            }
        )
        for offset in range(count)
    ]


class TestCrossRunKeyResolution:
    """Two runs of one set carrying the same primary key: the later run's row must be the one in the
    table, exactly as when the loader takes the runs one batch at a time. deltalite refuses a source
    batch with a repeated key, so the writer's keep-last deduplication over the concatenated set is
    what makes the write both possible and correct."""

    _SEED = pa.table({"id": [1, 2], "name": ["seed_1", "seed_2"]})
    _BATCHES = {
        "s3://bucket/run-1/3.parquet": pa.table({"id": [1, 3], "name": ["from_run_1", "new_3"]}),
        "s3://bucket/run-2/0.parquet": pa.table({"id": [1, 4], "name": ["from_run_2", "new_4"]}),
    }

    @contextmanager
    def _real_local_table(self, table_path: str) -> Iterator[None]:
        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PROCESSOR}.posthoganalytics"))
            stack.enter_context(patch(f"{_PROCESSOR}.mark_batch_as_processed"))
            stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            stack.enter_context(patch(f"{_PROCESSOR}.read_parquet", side_effect=lambda path: self._BATCHES[path]))
            stack.enter_context(
                patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=lambda **kwargs: make_local_table_ref(table_path))
            )
            job_model = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()
            yield

    def _messages(self) -> list[dict[str, Any]]:
        return _run_messages("run-1", start=3, count=1, final=False) + _run_messages(
            "run-2", start=0, count=1, final=False, is_resume=True
        )

    def test_the_later_run_wins_a_key_both_runs_carry(self, tmp_path: Path) -> None:
        coalesced_path = str(tmp_path / "coalesced")
        serial_path = str(tmp_path / "serial")
        write_deltalake(coalesced_path, self._SEED)
        write_deltalake(serial_path, self._SEED)

        with self._real_local_table(coalesced_path):
            process_messages(self._messages())
        with self._real_local_table(serial_path):
            for message in self._messages():
                process_message(message)

        coalesced = DeltaTable(coalesced_path)
        rows = coalesced.to_pyarrow_table().sort_by("id")
        assert rows.column("id").to_pylist() == [1, 2, 3, 4]
        assert rows.column("name").to_pylist() == ["from_run_2", "seed_2", "new_3", "new_4"]
        assert rows.to_pydict() == DeltaTable(serial_path).to_pyarrow_table().sort_by("id").to_pydict()

        # One deltalite commit for the set (a MERGE would mean the delta-rs fallback wrote it), and
        # every member of every run is found in it.
        data_commits = [commit for commit in coalesced.history() if commit["operation"] != "SET TBLPROPERTIES"]
        assert [commit["operation"] for commit in data_commits] == ["WRITE", "WRITE"]
        set_commit = data_commits[0]
        assert commit_covers_batch(set_commit, "run-1", 3)
        assert commit_covers_batch(set_commit, "run-2", 0)
        assert not commit_covers_batch(set_commit, "run-2", 1)


class TestSourceCopiesHeldThroughTheUpsert:
    # Coalesced sets are sized by `_ARROW_COPIES_HELD`. If the loader keeps the set as read alive
    # next to its deduplicated copy, a set takes twice the memory its cap allows.

    _ROWS = 2_000

    @staticmethod
    def _batch(batch_no: int, ids: list[int]) -> pa.Table:
        return pa.table({"id": ids, "payload": [f"{batch_no}:{pos:0>200}" for pos in range(len(ids))]})

    @pytest.mark.parametrize(
        "batch_ids",
        [
            [list(range(0, _ROWS)), list(range(_ROWS, 2 * _ROWS))],
            [[*range(0, _ROWS), 0, 1], list(range(_ROWS, 2 * _ROWS))],
            [list(range(0, _ROWS)), list(range(_ROWS // 2, _ROWS + _ROWS // 2))],
        ],
        ids=["unique_keys", "key_repeated_in_one_batch", "keys_repeated_across_the_set"],
    )
    def test_the_upsert_gets_one_copy_of_the_set_with_the_last_row_of_each_key(
        self, batch_ids: list[list[int]], tmp_path: Path
    ) -> None:
        table_path = str(tmp_path / "table")
        write_deltalake(table_path, self._batch(9, [0]))
        paths = [f"s3://bucket/run-1/{3 + n}.parquet" for n in range(len(batch_ids))]
        expected = pa.concat_tables([self._batch(n, ids) for n, ids in enumerate(batch_ids)]).to_pylist()
        last_row_by_id = {row["id"]: row for row in expected}
        expected_rows = sorted(last_row_by_id.values(), key=lambda row: expected.index(row))
        one_copy_bytes = pa.concat_tables([self._batch(n, ids) for n, ids in enumerate(batch_ids)]).nbytes
        seen: dict[str, Any] = {}

        async def record_upsert_source(writer: DeltaWriter, **kwargs: Any) -> bool:
            seen["held_bytes"] = pa.total_allocated_bytes() - baseline
            seen["rows"] = kwargs["data"].select(["id", "payload"]).to_pylist()
            return False

        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PROCESSOR}.posthoganalytics"))
            stack.enter_context(patch(f"{_PROCESSOR}.mark_batch_as_processed"))
            stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            stack.enter_context(
                patch(
                    f"{_PROCESSOR}.read_parquet",
                    side_effect=lambda path: self._batch(paths.index(path), batch_ids[paths.index(path)]),
                )
            )
            stack.enter_context(
                patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=lambda **kwargs: make_local_table_ref(table_path))
            )
            stack.enter_context(patch.object(DeltaWriter, "_write_via_deltalite", record_upsert_source))
            job_model = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()
            baseline = pa.total_allocated_bytes()
            process_messages(_run_messages("run-1", start=3, count=len(batch_ids), final=False))

        assert seen["rows"] == expected_rows
        assert seen["held_bytes"] < one_copy_bytes * 1.5
        landed = DeltaTable(table_path).to_pyarrow_table().select(["id", "payload"]).sort_by("id").to_pylist()
        assert landed == sorted(expected_rows, key=lambda row: row["id"])

    @parameterized.expand(
        [
            ("no_partition_column", None, [1, 2]),
            ("key_in_one_partition", ["p0", "p0", "p0"], [1, 2]),
            # The writer keys on the partition too, so a key that moved partition lands in both.
            ("key_moved_partition", ["p0", "p0", "p1"], [0, 1, 2]),
        ]
    )
    def test_dedupe_before_write_keeps_what_the_writer_keeps(
        self, _name: str, partitions: list[str] | None, kept_positions: list[int]
    ) -> None:
        columns: dict[str, list[Any]] = {"id": [1, 2, 1], "pos": [0, 1, 2]}
        if partitions is not None:
            columns[PARTITION_KEY] = partitions

        result = _dedupe_before_write(pa.table(columns), ["id"])

        assert result.column("pos").to_pylist() == kept_positions


class TestPostImportTrigger:
    """The V3 hand-off to `data-import-post-import`: without it the load-dependent
    post-import steps (signals, enrichment, statistics, table size, DuckLake copy)
    never run for V3 syncs."""

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}._trigger_ducklake_register_data_imports")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(f"{_PROCESSOR}.run_post_load_operations", new_callable=AsyncMock, return_value=_POST_LOAD_RESULT)
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_final_batch_triggers_post_import_once(
        self,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _post_load: AsyncMock,
        mock_mark_completed: MagicMock,
        _ducklake: MagicMock,
        mock_trigger: MagicMock,
        _mark_processed: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        helper = mock_helper_cls.return_value
        helper.get_delta_table = AsyncMock(return_value=None)
        mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_message(_message(is_final_batch=True))

        mock_mark_completed.assert_called_once()
        mock_trigger.assert_called_once()

    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(
        f"{_PROCESSOR}._run_post_load_for_already_processed_batch", return_value=PostLoadResult(queryable_folder=None)
    )
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_redelivered_final_batch_triggers_post_import(
        self,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        _already: MagicMock,
        _post_load: MagicMock,
        _mark_completed: MagicMock,
        mock_trigger: MagicMock,
        _analytics: MagicMock,
    ) -> None:
        # A writer crash between the final batch's Delta commit and the trigger means the
        # redelivery is the only chance to hand off — the trigger must fire on this path too.
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_message(_message(is_final_batch=True))

        mock_trigger.assert_called_once()

    @parameterized.expand(
        [
            ("cdc_sync_type", "cdc", None),
            ("scd2_companion_write", "incremental", "scd2_append"),
        ]
    )
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_cdc_finals_do_not_trigger_post_import(
        self, _case: str, sync_type: str, cdc_write_mode: str | None, mock_connect: AsyncMock
    ) -> None:
        # CDC finals land once per flush tick; triggering per tick would spam the fan-out.
        signal = MagicMock()
        signal.sync_type = sync_type
        signal.cdc_write_mode = cdc_write_mode

        _trigger_post_import_workflow(signal)

        mock_connect.assert_not_called()

    @parameterized.expand(
        [
            # Any start failure (e.g. no Temporal env vars on the load deployment) must
            # not fail the load; it is logged and captured.
            ("start_failure_is_captured", RuntimeError("no temporal"), True, 1),
            # An id collision means a register is already in flight for this schema.
            ("already_started_is_benign", WorkflowAlreadyStartedError("wf-id", "wf-type"), False, 1),
            # A genuine cancellation must not be mistaken for the client-side timeout that also
            # reports CANCELLED — only the "Timeout expired" / "operation was canceled" phrases
            # are transient, so this one is captured on the first attempt, not retried.
            ("genuine_cancel_is_captured", RPCError("Cancelled by caller", RPCStatusCode.CANCELLED, b""), True, 1),
        ]
    )
    @patch(f"{_PROCESSOR}.capture_exception")
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_trigger_failures_never_fail_the_load(
        self,
        _case: str,
        error: Exception,
        expect_captured: bool,
        expected_attempts: int,
        mock_connect: AsyncMock,
        mock_capture: MagicMock,
    ) -> None:
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=error)
        mock_connect.return_value = client

        signal = MagicMock()
        signal.sync_type = "incremental"
        signal.cdc_write_mode = None
        signal.team_id = 1
        signal.job_id = "job-1"
        signal.schema_id = "schema-1"
        signal.source_id = "source-1"

        _trigger_post_import_workflow(signal)

        assert client.start_workflow.call_count == expected_attempts
        assert mock_capture.called is expect_captured

    def _signal(self) -> MagicMock:
        signal = MagicMock()
        signal.sync_type = "incremental"
        signal.cdc_write_mode = None
        signal.team_id = 1
        signal.job_id = "job-1"
        signal.schema_id = "schema-1"
        signal.source_id = "source-1"
        return signal

    @parameterized.expand(
        [
            ("deadline_exceeded", RPCError("Timeout expired", RPCStatusCode.DEADLINE_EXCEEDED, b"")),
            # tonic cancels a call that outruns the client's own RPC deadline and reports it as
            # CANCELLED with this message, not DEADLINE_EXCEEDED — the status a bare-frontend
            # timeout produces. Must be ridden out the same way, not dropped on the first blip.
            ("client_side_cancel", RPCError("Timeout expired", RPCStatusCode.CANCELLED, b"")),
            ("lost_connection", RPCError("operation was canceled", RPCStatusCode.CANCELLED, b"")),
        ]
    )
    @patch(f"{_PROCESSOR}.capture_exception")
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_transient_rpc_timeout_is_retried_and_recovers(
        self,
        _case: str,
        error: RPCError,
        mock_connect: AsyncMock,
        mock_capture: MagicMock,
    ) -> None:
        # This start runs as a bare client RPC outside a Temporal workflow, so it gets
        # none of the server-side retry a `workflow.start_child_workflow` command would
        # have — a single transient timeout must not drop the trigger permanently.
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=[error, None])
        mock_connect.return_value = client

        _trigger_post_import_workflow(self._signal())

        assert client.start_workflow.call_count == 2
        mock_capture.assert_not_called()

    @patch(f"{_PROCESSOR}.capture_exception")
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_transient_connect_failure_is_retried_and_recovers(
        self,
        mock_connect: AsyncMock,
        mock_capture: MagicMock,
    ) -> None:
        # async_connect() itself can fail transiently (e.g. a DNS blip reaching the Temporal
        # frontend), raising the Rust bridge's untyped RuntimeError before any client exists —
        # this must be retried like an RPCError, not drop the trigger on the first blip.
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=None)
        mock_connect.side_effect = [RuntimeError("Failed client connect: Server connection error: ..."), client]

        _trigger_post_import_workflow(self._signal())

        assert mock_connect.call_count == 2
        mock_capture.assert_not_called()

    @parameterized.expand([("size_written", True), ("size_not_written", False)])
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_tells_the_workflow_whether_post_load_wrote_the_table_size(
        self, _case: str, table_size_written: bool, mock_connect: AsyncMock
    ) -> None:
        # The workflow skips its size activity on True. A dropped False would leave a table that
        # post-load could not size with no size at all.
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=None)
        mock_connect.return_value = client

        _trigger_post_import_workflow(self._signal(), table_size_written)

        assert client.start_workflow.await_args is not None
        assert client.start_workflow.await_args.args[1].table_size_written is table_size_written

    @patch(f"{_PROCESSOR}.capture_exception")
    @patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock)
    def test_persistent_rpc_timeout_is_captured_after_retries_exhausted(
        self,
        mock_connect: AsyncMock,
        mock_capture: MagicMock,
    ) -> None:
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=RPCError("Timeout expired", RPCStatusCode.DEADLINE_EXCEEDED, b""))
        mock_connect.return_value = client

        _trigger_post_import_workflow(self._signal())

        assert client.start_workflow.call_count == 3
        mock_capture.assert_called_once()
        # tenacity defaults to wrapping the last attempt in a RetryError once retries are
        # exhausted; `reraise=True` must be set so the underlying RPCError reaches capture
        # instead, keeping the error-tracking issue actionable.
        captured_exception = mock_capture.call_args[0][0]
        assert isinstance(captured_exception, RPCError)


# Regression guard for #70476: pyarrow 21+ string_view broke delta pushdown on string PKs.
class TestEnrichCdcRows:
    """Cross-batch CDC enrichment against a real local Delta table."""

    @staticmethod
    def _batch(rows: list[dict[str, Any]]) -> pa.Table:
        return pa.table(
            {
                "id": pa.array([r["id"] for r in rows], pa.int64()),
                "name": pa.array([r.get("name") for r in rows], pa.string()),
                "big": pa.array([r.get("big") for r in rows], pa.string()),
                CDC_OP_COLUMN: pa.array([r["op"] for r in rows], pa.string()),
                TOAST_OMITTED_COLUMN: pa.array([r.get("omitted") for r in rows], pa.list_(pa.string())),
            }
        )

    def _stamped(self, ids: list[int], ops: list[str], seqs: list[int]) -> pa.Table:
        from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_PROVENANCE

        table = pa.table(
            {
                "id": pa.array(ids, pa.int64()),
                "name": pa.array([f"n{i}" for i in ids], pa.string()),
                CDC_OP_COLUMN: pa.array(ops, pa.string()),
            }
        )
        return table.append_column(
            pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE), pa.array(seqs, pa.int64())
        )

    def _resolve(self, table: pa.Table, *, cdc_write_mode: str = "incremental_merge"):
        return _resolve_cdc_positions(
            table,
            primary_keys=["id"],
            cdc_write_mode=cdc_write_mode,
        )

    def test_the_merge_lane_collapses_a_key_to_its_latest_version(self):
        # The write engine rejects duplicate keys outright.
        table = self._stamped([1, 1, 2], ["I", "U", "I"], [10, 20, 30])
        result = self._resolve(table)

        assert result.column(CDC_SEQ_COLUMN).to_pylist() == [20, 30]

    def test_resolution_is_skipped_without_an_engine_stamped_position(self):
        # A source column named _ph_cdc_seq must not drive the guard.
        table = self._stamped([1, 1], ["I", "U"], [10, 20]).drop_columns([CDC_SEQ_COLUMN])
        table = table.append_column(pa.field(CDC_SEQ_COLUMN, pa.int64()), pa.array([10, 20], pa.int64()))
        result = self._resolve(table)

        assert result is table

    def test_the_history_lane_keeps_every_version_of_a_key(self):
        table = self._stamped([1, 1], ["I", "U"], [10, 20])
        result = self._resolve(table, cdc_write_mode="scd2_append")

        assert result.column(CDC_SEQ_COLUMN).to_pylist() == [10, 20]

    def _write_existing(self, path: str) -> None:
        write_deltalake(
            path,
            pa.table(
                {
                    "id": pa.array([1], pa.int64()),
                    "name": pa.array(["one"], pa.string()),
                    "big": pa.array(["toasted-1"], pa.string()),
                }
            ),
            mode="overwrite",
        )

    def test_verification_stays_quiet_when_enrichment_filled_the_delete(self):
        with tempfile.TemporaryDirectory() as path:
            self._write_existing(path)

            with patch(f"{_PROCESSOR}.CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL") as violations:
                _enrich_cdc_rows(
                    self._batch([{"id": 1, "op": "D"}]),
                    primary_keys=["id"],
                    cdc_write_mode="incremental_merge",
                    existing_delta_table=DeltaTable(path),
                    batch_index=0,
                    verify_deletes=True,
                )

            violations.inc.assert_not_called()

    def test_verification_reports_a_delete_that_would_null_target_data(self):
        with tempfile.TemporaryDirectory() as path:
            self._write_existing(path)

            # Enrichment silently doing nothing is the failure this lane exists to catch: under
            # deltalite the upsert replaces the whole row, so those nulls would land in the table.
            with (
                patch(f"{_PROCESSOR}.enrich_delete_rows", side_effect=lambda table, *_a, **_kw: table),
                patch(f"{_PROCESSOR}.CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL") as violations,
            ):
                _enrich_cdc_rows(
                    self._batch([{"id": 1, "op": "D"}]),
                    primary_keys=["id"],
                    cdc_write_mode="incremental_merge",
                    existing_delta_table=DeltaTable(path),
                    batch_index=0,
                    verify_deletes=True,
                )

            violations.inc.assert_called_once_with(1)

    def test_verification_is_skipped_when_the_flag_is_off(self):
        with tempfile.TemporaryDirectory() as path:
            self._write_existing(path)

            with (
                patch(f"{_PROCESSOR}.enrich_delete_rows", side_effect=lambda table, *_a, **_kw: table),
                patch(f"{_PROCESSOR}.verify_delete_enrichment") as verify,
            ):
                _enrich_cdc_rows(
                    self._batch([{"id": 1, "op": "D"}]),
                    primary_keys=["id"],
                    cdc_write_mode="incremental_merge",
                    existing_delta_table=DeltaTable(path),
                    batch_index=0,
                )

            verify.assert_not_called()

    def test_fills_toast_and_delete_rows_from_delta_state_and_drops_marker(self):
        with tempfile.TemporaryDirectory() as path:
            write_deltalake(
                path,
                pa.table(
                    {
                        "id": pa.array([1, 2], pa.int64()),
                        "name": pa.array(["one", "two"], pa.string()),
                        "big": pa.array(["toasted-1", "toasted-2"], pa.string()),
                    }
                ),
                mode="overwrite",
            )

            batch = self._batch(
                [
                    {"id": 1, "op": "U", "name": "renamed", "omitted": ["big"]},
                    {"id": 2, "op": "D"},
                ]
            )
            result = _enrich_cdc_rows(
                batch,
                primary_keys=["id"],
                cdc_write_mode="incremental_merge",
                existing_delta_table=DeltaTable(path),
                batch_index=0,
            )

            # The unchanged-TOAST column keeps its persisted value instead of
            # merging NULL over it; the DELETE row is enriched as before.
            assert result.column("big").to_pylist() == ["toasted-1", "toasted-2"]
            assert result.column("name").to_pylist() == ["renamed", "two"]
            assert TOAST_OMITTED_COLUMN not in result.column_names

    def test_scd2_fill_uses_current_row_not_history(self):
        with tempfile.TemporaryDirectory() as path:
            ts = pa.timestamp("us", tz="UTC")
            write_deltalake(
                path,
                pa.table(
                    {
                        "id": pa.array([1, 1], pa.int64()),
                        "name": pa.array(["v1", "v2"], pa.string()),
                        "big": pa.array(["old-toast", "current-toast"], pa.string()),
                        SCD2_VALID_TO_COLUMN: pa.array([1_000_000, None], ts),
                    }
                ),
                mode="overwrite",
            )

            batch = self._batch([{"id": 1, "op": "U", "name": "v3", "omitted": ["big"]}])
            result = _enrich_cdc_rows(
                batch,
                primary_keys=["id"],
                cdc_write_mode="scd2_append",
                existing_delta_table=DeltaTable(path),
                batch_index=0,
            )

            assert result.column("big").to_pylist() == ["current-toast"]

    def test_composite_pk_delete_enrichment_with_no_matching_existing_row(self):
        # Existing row shares the first PK component ("id") with the incoming DELETE
        # but not the full composite key, so `match_indices` narrows to empty. This
        # used to crash with ArrowNotImplementedError: `Table.take([])` infers a
        # null-typed indices array, and pyarrow has no take kernel for (string, null).
        with tempfile.TemporaryDirectory() as path:
            write_deltalake(
                path,
                pa.table(
                    {
                        "id": pa.array([1], pa.int64()),
                        "tenant": pa.array(["a"], pa.string()),
                        "name": pa.array(["existing"], pa.string()),
                    }
                ),
                mode="overwrite",
            )

            batch = pa.table(
                {
                    "id": pa.array([1], pa.int64()),
                    "tenant": pa.array(["z"], pa.string()),
                    "name": pa.array([None], pa.string()),
                    CDC_OP_COLUMN: pa.array(["D"], pa.string()),
                    TOAST_OMITTED_COLUMN: pa.array([None], pa.list_(pa.string())),
                }
            )
            result = _enrich_cdc_rows(
                batch,
                primary_keys=["id", "tenant"],
                cdc_write_mode="incremental_merge",
                existing_delta_table=DeltaTable(path),
                batch_index=0,
            )

            assert TOAST_OMITTED_COLUMN not in result.column_names
            assert result.column("name").to_pylist() == [None]

    def test_composite_pk_delete_enrichment_when_existing_table_lacks_a_pk_column(self):
        # The existing Delta table predates a composite key gaining a second PK
        # column ("tenant"), so it can't be exactly matched. Same bug as above but
        # via the `else` branch, which also called `.take([])` unconditionally.
        with tempfile.TemporaryDirectory() as path:
            write_deltalake(
                path,
                pa.table(
                    {
                        "id": pa.array([1], pa.int64()),
                        "name": pa.array(["existing"], pa.string()),
                    }
                ),
                mode="overwrite",
            )

            batch = pa.table(
                {
                    "id": pa.array([1], pa.int64()),
                    "tenant": pa.array(["z"], pa.string()),
                    "name": pa.array([None], pa.string()),
                    CDC_OP_COLUMN: pa.array(["D"], pa.string()),
                    TOAST_OMITTED_COLUMN: pa.array([None], pa.list_(pa.string())),
                }
            )
            result = _enrich_cdc_rows(
                batch,
                primary_keys=["id", "tenant"],
                cdc_write_mode="incremental_merge",
                existing_delta_table=DeltaTable(path),
                batch_index=0,
            )

            assert TOAST_OMITTED_COLUMN not in result.column_names
            assert result.column("name").to_pylist() == [None]

    def test_marker_dropped_when_enrichment_cannot_run(self):
        # First-ever CDC batch: no existing Delta table to fill from. The value is
        # unknowable (stays null) but the transport marker must never reach the write.
        batch = self._batch([{"id": 1, "op": "U", "name": "renamed", "omitted": ["big"]}])
        result = _enrich_cdc_rows(
            batch,
            primary_keys=["id"],
            cdc_write_mode="incremental_merge",
            existing_delta_table=None,
            batch_index=0,
        )

        assert TOAST_OMITTED_COLUMN not in result.column_names
        assert result.column("big").to_pylist() == [None]


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


def _post_load_summary(mock_logger: MagicMock) -> dict[str, Any]:
    summaries = [call.kwargs for call in mock_logger.info.call_args_list if call.args == (SUMMARY_EVENT,)]
    assert len(summaries) == 1
    return summaries[0]


class TestBatchPhaseReports:
    @patch(f"{_PROCESSOR}.logger")
    @patch(f"{_PROCESSOR}.report_phase")
    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}.mark_batch_as_processed")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(
        f"{_PROCESSOR}.run_post_load_operations",
        new_callable=AsyncMock,
        return_value=PostLoadResult(queryable_folder=None),
    )
    @patch(f"{_PROCESSOR}.read_parquet", return_value=pa.table({"id": [1]}))
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False)
    @patch(f"{_PROCESSOR}.DeltaWriter")
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    def test_a_fresh_final_batch_reports_each_phase_in_order(
        self,
        mock_job_model: MagicMock,
        mock_helper_cls: MagicMock,
        mock_writer_cls: MagicMock,
        _already: MagicMock,
        _read: MagicMock,
        _post_load: AsyncMock,
        _mark_completed: MagicMock,
        _mark_processed: MagicMock,
        _trigger: MagicMock,
        _analytics: MagicMock,
        mock_report_phase: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        async def post_load(**_kwargs: Any) -> PostLoadResult:
            with post_load_phase("delta_maintenance"):
                return PostLoadResult(queryable_folder=None)

        _post_load.side_effect = post_load
        delta_table = MagicMock()
        delta_table.schema.return_value = pa.schema([pa.field("id", pa.int64())])
        delta_table.file_uris.return_value = []
        mock_helper_cls.return_value.get_delta_table = AsyncMock(return_value=None)
        mock_writer_cls.return_value.write = AsyncMock(return_value=delta_table)
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_message(_message(is_final_batch=True, batch_index=4, run_uuid="run-9"))

        assert [call.args[0] for call in mock_report_phase.call_args_list] == [
            "deliver",
            "read",
            "write",
            "post_load",
            "finalize",
        ]
        summary = _post_load_summary(mock_logger)
        assert summary["phase_names"] == ["delta_maintenance", "job_completion", "post_import_trigger"]
        assert (summary["external_data_job_id"], summary["run_uuid"], summary["outcome"]) == ("job-1", "run-9", "ok")

    @patch(f"{_PROCESSOR}.logger")
    @patch(f"{_PROCESSOR}.report_phase")
    @patch(f"{_PROCESSOR}.posthoganalytics")
    @patch(f"{_PROCESSOR}._trigger_post_import_workflow")
    @patch(f"{_PROCESSOR}._mark_job_completed")
    @patch(
        f"{_PROCESSOR}._run_post_load_for_already_processed_batch", return_value=PostLoadResult(queryable_folder=None)
    )
    @patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=True)
    @patch(f"{_PROCESSOR}.DeltaTableRef")
    @patch(f"{_PROCESSOR}.ExternalDataJob")
    @patch(f"{_PROCESSOR}.close_old_connections")
    def test_a_redelivered_final_batch_reports_post_load_and_finalize_only(
        self,
        _close: MagicMock,
        mock_job_model: MagicMock,
        _helper_cls: MagicMock,
        _already: MagicMock,
        _post_load: MagicMock,
        _mark_completed: MagicMock,
        _trigger: MagicMock,
        _analytics: MagicMock,
        mock_report_phase: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()

        process_message(_message(is_final_batch=True))

        assert [call.args[0] for call in mock_report_phase.call_args_list] == ["deliver", "post_load", "finalize"]
        assert _post_load_summary(mock_logger)["phase_names"] == ["job_completion", "post_import_trigger"]


_WORKFLOW_RUN = "0190aaaa-0000-7000-8000-000000000001"


class TestTableRebuildLoad:
    # Batches of 3 keys each. `_SOURCE_REPEATS_A_KEY` holds key 4 in two batches.
    _SOURCE = [{"id": [1, 2, 3]}, {"id": [4, 5, 6]}, {"id": [7, 8, 9]}]
    _SOURCE_REPEATS_A_KEY = [{"id": [1, 2, 3]}, {"id": [4, 5, 6]}, {"id": [4, 8, 9]}]

    @staticmethod
    def _rows(run_uuid: str, index: int, ids: list[int]) -> pa.Table:
        return pa.table({"id": ids, "name": [f"{run_uuid[-2:]}_b{index}_{row_id}" for row_id in ids]})

    @contextmanager
    def _loader(self, table_path: str, batches: dict[str, pa.Table], config: dict[str, Any]) -> Iterator[None]:
        def local_ref(**kwargs: Any) -> DeltaTableRef:
            ref = make_local_table_ref(table_path)
            ref._is_first_sync = kwargs["is_first_sync"]
            return ref

        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PROCESSOR}.posthoganalytics"))
            stack.enter_context(patch(f"{_PROCESSOR}.mark_batch_as_processed"))
            stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            stack.enter_context(patch(f"{_PROCESSOR}.read_parquet", side_effect=lambda path: batches[path]))
            stack.enter_context(patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=local_ref))
            job_model = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            job = MagicMock()
            job.schema.sync_type_config = config
            job_model.objects.prefetch_related.return_value.get.return_value = job
            yield

    def _load(
        self,
        table_path: str,
        attempt: int,
        source: list[dict[str, list[int]]],
        *,
        rebuild: bool,
        indexes: list[int] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        run_uuid = f"{_WORKFLOW_RUN}-a{attempt}"
        batches = {
            f"s3://bucket/{run_uuid}/{index}": self._rows(run_uuid, index, rows["id"])
            for index, rows in enumerate(source)
        }
        with self._loader(table_path, batches, config if config is not None else {}):
            for index in indexes if indexes is not None else range(len(source)):
                process_message(
                    _message(
                        run_uuid=run_uuid,
                        batch_index=index,
                        s3_path=f"s3://bucket/{run_uuid}/{index}",
                        is_first_ever_sync=rebuild,
                    )
                )

    @staticmethod
    def _table_rows(table_path: str) -> list[tuple[int, str]]:
        rows = DeltaTable(table_path).to_pyarrow_table().to_pydict()
        return sorted(zip(rows["id"], rows["name"]))

    @parameterized.expand(
        [
            ("one_attempt", []),
            ("an_attempt_replaced_after_two_batches", [0, 1]),
            ("an_attempt_replaced_before_its_first_batch_loads", []),
        ]
    )
    def test_a_rebuild_gives_the_table_that_a_merge_of_each_batch_gives(
        self, case: str, first_attempt_batches: list[int]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt, merged = f"{tmp}/rebuilt", f"{tmp}/merged"
            last_attempt = 1 if case == "one_attempt" else 2
            config: dict[str, Any] = {}

            if last_attempt == 2:
                self._load(rebuilt, 1, self._SOURCE, rebuild=True, indexes=first_attempt_batches, config=config)
                config["table_rebuild_run_uuid"] = f"{_WORKFLOW_RUN}-a2"
            self._load(rebuilt, last_attempt, self._SOURCE, rebuild=True, indexes=[0, 1], config=config)
            if last_attempt == 2:
                # A batch of the first attempt that the loader takes after the second attempt started.
                self._load(rebuilt, 1, self._SOURCE, rebuild=True, indexes=[2], config=config)
            self._load(rebuilt, last_attempt, self._SOURCE, rebuild=True, indexes=[2], config=config)

            self._load(merged, last_attempt, self._SOURCE, rebuild=False)

            assert len(self._table_rows(rebuilt)) == 9
            assert self._table_rows(rebuilt) == self._table_rows(merged)
            operations = [commit["operation"] for commit in DeltaTable(rebuilt).history()]
            assert "MERGE" not in operations

    def test_a_run_after_the_rebuild_merges_on_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._load(tmp, 1, self._SOURCE, rebuild=True)
            later = pa.table({"id": [9, 10], "name": ["later_9", "later_10"]})
            with self._loader(tmp, {"s3://bucket/later/0": later}, {"table_rebuild_run_uuid": f"{_WORKFLOW_RUN}-a1"}):
                process_message(_message(run_uuid="0190bbbb-a1", batch_index=0, s3_path="s3://bucket/later/0"))

            rows = dict(self._table_rows(tmp))
            assert len(self._table_rows(tmp)) == 10
            assert (rows[9], rows[10]) == ("later_9", "later_10")

    def test_a_key_that_the_source_holds_twice_stays_twice_until_a_later_run_merges_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._load(tmp, 1, self._SOURCE_REPEATS_A_KEY, rebuild=True)
            assert [name for row_id, name in self._table_rows(tmp) if row_id == 4] == ["a1_b1_4", "a1_b2_4"]

            later = pa.table({"id": [4], "name": ["later_4"]})
            with self._loader(tmp, {"s3://bucket/later/0": later}, {}):
                process_message(_message(run_uuid="0190bbbb-a1", batch_index=0, s3_path="s3://bucket/later/0"))

            assert [name for row_id, name in self._table_rows(tmp) if row_id == 4] == ["later_4"]


FileRows = dict[str, list[int]]


class TestReplaceScopeLoad:
    # The table before the run: the rows of three files of the bucket.
    _SEED: FileRows = {"a.csv": [1, 2], "b.csv": [3, 4], "c.csv": [5]}

    @staticmethod
    def _table(file_rows: FileRows) -> pa.Table:
        if not file_rows:
            # What the pipeline queues for a run that read no rows.
            return pa.table({"_file_name": pa.array([], pa.string())})
        names = [name for name, ids in file_rows.items() for _ in ids]
        ids = [row_id for row_ids in file_rows.values() for row_id in row_ids]
        return pa.table({"_file_name": pa.array(names, pa.string()), "id": pa.array(ids, pa.int64())})

    @contextmanager
    def _loader(
        self, table_path: str, files: dict[str, pa.Table], config: dict[str, Any], *, redis: bool = False
    ) -> Iterator[None]:
        def local_ref(**kwargs: Any) -> DeltaTableRef:
            ref = make_local_table_ref(table_path)
            ref._is_first_sync = kwargs["is_first_sync"]
            return ref

        def update_config(*args: Any, updates: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            config.update(updates)
            return config

        @contextmanager
        def no_redis() -> Iterator[None]:
            yield None

        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PROCESSOR}.posthoganalytics"))
            stack.enter_context(patch(f"{_PROCESSOR}.mark_batch_as_processed"))
            if not redis:
                # The redelivery check then reads the table history, which is what finds a landed write.
                stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            stack.enter_context(patch(f"{_IDEMPOTENCY}.get_redis_client", no_redis))
            for module in (_PROCESSOR, _REPLACE_ROWS):
                stack.enter_context(patch(f"{module}.read_parquet", side_effect=lambda path: files[path]))
            stack.enter_context(patch(f"{_REPLACE_SCOPE}.update_sync_type_config_keys", side_effect=update_config))
            stack.enter_context(patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=local_ref))
            job_model = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            job = MagicMock()
            job.schema.sync_type_config = config
            job_model.objects.prefetch_related.return_value.get.return_value = job
            yield

    def _load(
        self,
        table_path: str,
        attempt: int,
        batches: list[FileRows],
        scope: ReplaceScope,
        *,
        indexes: list[int] | None = None,
        config: dict[str, Any] | None = None,
        is_first_ever_sync: bool = False,
        delivery: int = 1,
        redis: bool = False,
    ) -> None:
        run_uuid = f"{_WORKFLOW_RUN}-a{attempt}"
        manifest_path = f"s3://bucket/{run_uuid}/replace_scope.parquet"
        files = {f"s3://bucket/{run_uuid}/{index}": self._table(rows) for index, rows in enumerate(batches)}
        files[manifest_path] = manifest_table(scope)
        with self._loader(table_path, files, config if config is not None else {}, redis=redis):
            for index in indexes if indexes is not None else range(len(batches)):
                process_message(
                    _message(
                        run_uuid=run_uuid,
                        batch_index=index,
                        s3_path=f"s3://bucket/{run_uuid}/{index}",
                        primary_keys=None,
                        is_first_ever_sync=is_first_ever_sync,
                        replace_scope={"column": "_file_name", "manifest_path": manifest_path},
                    ),
                    attempt=delivery,
                )

    @staticmethod
    def _scope(replaced: set[str], retained: set[str]) -> ReplaceScope:
        return ReplaceScope(column="_file_name", replaced=frozenset(replaced), retained=frozenset(retained))

    @staticmethod
    def _rows_by_file(table_path: str) -> FileRows:
        rows: FileRows = {}
        for name, row_id in sorted(
            zip(*DeltaTable(table_path).to_pyarrow_table().select(["_file_name", "id"]).to_pydict().values())
        ):
            rows.setdefault(name, []).append(row_id)
        return rows

    @staticmethod
    def _operations(table_path: str) -> list[str]:
        return [commit["operation"] for commit in DeltaTable(table_path).history()]

    @parameterized.expand(
        [
            ("a_deleted_file_loses_its_rows", [{}], set(), {"a.csv", "c.csv"}, {"a.csv": [1, 2], "c.csv": [5]}),
            (
                "a_shrunk_file_keeps_only_its_new_rows_and_a_new_file_adds_its_rows",
                [{"b.csv": [3]}, {"d.csv": [7, 8]}],
                {"b.csv", "d.csv"},
                {"a.csv", "b.csv", "c.csv", "d.csv"},
                {"a.csv": [1, 2], "b.csv": [3], "c.csv": [5], "d.csv": [7, 8]},
            ),
        ]
    )
    def test_the_table_mirrors_the_files_of_the_scope(
        self, _name: str, batches: list[FileRows], replaced: set[str], retained: set[str], expected: FileRows
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_deltalake(tmp, self._table(self._SEED))

            self._load(tmp, 1, batches, self._scope(replaced, retained))

            assert self._rows_by_file(tmp) == expected
            assert "MERGE" not in self._operations(tmp)

    @parameterized.expand(
        [
            ("an_attempt_replaced_after_two_batches", [0, 1]),
            ("an_attempt_replaced_before_its_first_batch_loads", []),
        ]
    )
    def test_a_retried_run_gives_the_table_of_one_attempt(self, _name: str, first_attempt_batches: list[int]) -> None:
        batches: list[FileRows] = [{"b.csv": [3]}, {"d.csv": [7]}, {"e.csv": [9]}]
        scope = self._scope({"b.csv", "d.csv", "e.csv"}, {"a.csv", "b.csv", "c.csv", "d.csv", "e.csv"})
        with tempfile.TemporaryDirectory() as tmp:
            retried, once = f"{tmp}/retried", f"{tmp}/once"
            write_deltalake(retried, self._table(self._SEED))
            write_deltalake(once, self._table(self._SEED))
            config: dict[str, Any] = {}

            self._load(retried, 1, batches, scope, indexes=first_attempt_batches, config=config)
            self._load(retried, 2, batches, scope, indexes=[0], config=config)
            # A batch of the first attempt that the loader takes after the second attempt started.
            self._load(retried, 1, batches, scope, indexes=[2], config=config)
            self._load(retried, 2, batches, scope, indexes=[1, 2], config=config)
            self._load(once, 1, batches, scope)

            assert self._rows_by_file(retried) == self._rows_by_file(once)
            assert self._rows_by_file(once) == {"a.csv": [1, 2], "b.csv": [3], "c.csv": [5], "d.csv": [7], "e.csv": [9]}

    def test_a_first_batch_redelivered_after_its_deletes_still_writes(self) -> None:
        scope = self._scope({"b.csv"}, {"a.csv", "b.csv", "c.csv"})
        original_write = DeltaWriter.write

        async def worker_dies_once(writer: DeltaWriter, **kwargs: Any) -> DeltaTable:
            if not crashed:
                crashed.append(True)
                raise RuntimeError("the worker died before the write")
            return await original_write(writer, **kwargs)

        crashed: list[bool] = []
        with tempfile.TemporaryDirectory() as tmp:
            write_deltalake(tmp, self._table(self._SEED))
            with patch.object(DeltaWriter, "write", worker_dies_once), pytest.raises(RuntimeError):
                self._load(tmp, 1, [{"b.csv": [3]}], scope, redis=True)
            assert "DELETE" in self._operations(tmp)

            with patch.object(DeltaWriter, "write", worker_dies_once):
                self._load(tmp, 1, [{"b.csv": [3]}], scope, delivery=2, redis=True)

            assert self._rows_by_file(tmp) == {"a.csv": [1, 2], "b.csv": [3], "c.csv": [5]}

    @parameterized.expand([("a_first_sync", True, True), ("no_table", False, False)])
    def test_nothing_is_deleted_without_rows_to_replace(
        self, _name: str, is_first_ever_sync: bool, seeded: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            if seeded:
                write_deltalake(tmp, self._table(self._SEED))

            self._load(
                tmp,
                1,
                [{"b.csv": [3]}],
                self._scope({"b.csv"}, {"b.csv"}),
                is_first_ever_sync=is_first_ever_sync,
            )

            assert self._rows_by_file(tmp) == {"b.csv": [3]}
            assert "DELETE" not in self._operations(tmp)

    def test_an_empty_batch_never_creates_a_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table_path = f"{tmp}/table"

            with pytest.raises(ValueError, match="is missing"):
                self._load(table_path, 1, [{}], self._scope(set(), {"a.csv"}))

            assert not DeltaTable.is_deltatable(table_path)


def _batch_rows(index: int) -> pa.Table:
    # Each batch updates one row of the batch before it and adds two rows.
    ids = [index * 2, index * 2 + 1, index * 2 + 2]
    return pa.table({"id": ids, "name": [f"batch_{index}_{row_id}" for row_id in ids]})


def _data_commits(table_path: str) -> list[tuple[str, str | None]]:
    commits = [commit for commit in DeltaTable(table_path).history() if commit["operation"] != "SET TBLPROPERTIES"]
    return [(commit["operation"], commit.get("batch_index")) for commit in reversed(commits)]


class TestTableHandleReuse:
    _SEED = pa.table({"id": [0, 1], "name": ["seed_0", "seed_1"]})

    @contextmanager
    def _loader(self, table_path: str, opens: list[int]) -> Iterator[None]:
        open_table = DeltaTableRef._open_delta_table

        async def counted_open(ref: DeltaTableRef) -> DeltaTable | None:
            opens.append(1)
            return await open_table(ref)

        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PROCESSOR}.posthoganalytics"))
            stack.enter_context(patch(f"{_PROCESSOR}.mark_batch_as_processed"))
            stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
            stack.enter_context(
                patch(f"{_PROCESSOR}.read_parquet", side_effect=lambda path: _batch_rows(int(path.rsplit("/", 1)[1])))
            )
            stack.enter_context(
                patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=lambda **kwargs: make_local_table_ref(table_path))
            )
            stack.enter_context(patch.object(DeltaTableRef, "_open_delta_table", counted_open))
            stack.enter_context(
                patch(f"{_PROCESSOR}.run_post_load_operations", new=AsyncMock(return_value=_POST_LOAD_RESULT))
            )
            stack.enter_context(patch(f"{_PROCESSOR}._complete_run"))
            job_model = stack.enter_context(patch(f"{_PROCESSOR}.ExternalDataJob"))
            job_model.objects.prefetch_related.return_value.get.return_value = MagicMock()
            yield

    @staticmethod
    def _batch(index: int, **overrides: Any) -> dict[str, Any]:
        return _message(**{"batch_index": index, "s3_path": f"s3://bucket/run-1/{index}", **overrides})

    @parameterized.expand(
        [
            ("append", "append", 1),
            ("merge", "incremental", 1),
            ("full_refresh", "full_refresh", 0),
        ]
    )
    def test_reuse_gives_the_table_and_the_commits_of_an_open_per_batch(
        self, _name: str, sync_type: str, first_index: int
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reused_path, opened_path = f"{tmp}/reused", f"{tmp}/opened"
            reused_opens: list[int] = []
            opened_opens: list[int] = []
            for table_path, opens, reuse in ((reused_path, reused_opens, True), (opened_path, opened_opens, False)):
                write_deltalake(table_path, self._SEED)
                with ExitStack() as stack:
                    stack.enter_context(self._loader(table_path, opens))
                    if not reuse:
                        stack.enter_context(patch.object(GroupTableHandles, "take", return_value=None))
                    for index in range(first_index, first_index + 4):
                        process_message(self._batch(index, sync_type=sync_type))

            assert (len(reused_opens), len(opened_opens)) == (1, 4)
            reused_rows = (
                DeltaTable(reused_path).to_pyarrow_table().sort_by([("id", "ascending"), ("name", "ascending")])
            )
            opened_rows = (
                DeltaTable(opened_path).to_pyarrow_table().sort_by([("id", "ascending"), ("name", "ascending")])
            )
            assert reused_rows.num_rows > self._SEED.num_rows
            assert reused_rows.to_pydict() == opened_rows.to_pydict()
            assert _data_commits(reused_path) == _data_commits(opened_path)

    @parameterized.expand(
        [
            ("redelivery", {"attempt": 2}, {}),
            ("another_run", {}, {"run_uuid": "run-2", "job_id": "job-2"}),
            ("another_resource", {}, {"resource_name": "other"}),
            ("batch_gap", {}, {"batch_index": 4}),
            ("same_batch_again", {}, {"batch_index": 2}),
            ("first_batch", {}, {"batch_index": 0, "is_resume": True}),
        ]
    )
    def test_a_batch_the_handle_was_not_kept_for_opens_the_table(
        self, _name: str, process_kwargs: dict[str, Any], overrides: dict[str, Any]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_deltalake(tmp, self._SEED)
            opens: list[int] = []
            with self._loader(tmp, opens):
                process_message(self._batch(2, sync_type="append"))
                process_message(self._batch(3, sync_type="append", **overrides), **process_kwargs)

            assert len(opens) == 2

    @parameterized.expand(
        [
            ("lease_lost",),
            ("read_failed",),
            ("final_batch",),
            ("group_run_ended",),
            ("waited_too_long",),
        ]
    )
    def test_the_handle_is_released(self, case: str) -> None:
        now = [0.0]
        handles = GroupTableHandles(max_idle_seconds=60.0, clock=lambda: now[0])

        def lose_lease() -> None:
            raise _LeaseLost()

        with tempfile.TemporaryDirectory() as tmp, patch(f"{_PROCESSOR}.GROUP_TABLE_HANDLES", handles):
            write_deltalake(tmp, self._SEED)
            opens: list[int] = []
            with self._loader(tmp, opens):
                process_message(self._batch(2, sync_type="append"))
                assert len(handles) == 1

                if case == "lease_lost":
                    with pytest.raises(_LeaseLost):
                        process_message(self._batch(3, sync_type="append"), verify_ownership=lose_lease)
                elif case == "read_failed":
                    with (
                        patch(f"{_PROCESSOR}.read_parquet", side_effect=OSError("read failed")),
                        pytest.raises(OSError),
                    ):
                        process_message(self._batch(3, sync_type="append"))
                elif case == "final_batch":
                    process_message(self._batch(3, sync_type="append", is_final_batch=True, total_rows=6))
                elif case == "group_run_ended":
                    handles.release(1, "schema-1")
                else:
                    now[0] = 61.0
                    process_message(self._batch(9, sync_type="append", schema_id="schema-2"))
                    handles.release(1, "schema-2")

                assert len(handles) == 0
                opens_before = len(opens)
                next_index = 4 if case == "final_batch" else 3
                process_message(self._batch(next_index, sync_type="append"))

            assert len(opens) == opens_before + 1

    def test_a_commit_from_another_writer_is_in_the_reused_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_deltalake(tmp, self._SEED)
            opens: list[int] = []
            seen_columns: list[list[str]] = []
            apply_partitioning = _apply_partitioning

            def record_snapshot(export_signal: Any, pa_table: pa.Table, existing: DeltaTable, schema: Any) -> pa.Table:
                seen_columns.append([field.name for field in existing.schema().fields])
                return apply_partitioning(export_signal, pa_table, existing, schema)

            with (
                self._loader(tmp, opens),
                patch(f"{_PROCESSOR}._apply_partitioning", side_effect=record_snapshot),
                patch(f"{_PROCESSOR}.logger") as mock_logger,
            ):
                process_message(self._batch(2, sync_type="append"))
                write_deltalake(
                    tmp, pa.table({"id": [100], "name": ["other"], "added": ["x"]}), mode="append", schema_mode="merge"
                )
                process_message(self._batch(3, sync_type="append"))

            assert len(opens) == 1
            assert seen_columns == [["id", "name"], ["id", "name", "added"]]
            written = [
                call.kwargs
                for call in mock_logger.debug.call_args_list
                if call.args[0] == "batch_written_to_delta_lake"
            ]
            assert [fields["table_handle"] for fields in written] == ["opened", "reused"]
            assert "table_open_ms" in written[0] and "table_refresh_ms" not in written[0]
            assert "table_refresh_ms" in written[1] and "table_open_ms" not in written[1]
            assert {"parquet_read_ms", "partition_ms", "schema_evolve_ms", "write_ms"} <= written[1].keys()
            rows = DeltaTable(tmp).to_pyarrow_table()
            assert rows.sort_by("id").column("id").to_pylist() == [0, 1, 4, 5, 6, 6, 7, 8, 100]
            assert rows.schema.names == ["id", "name", "added"]


class TestCompactionDuringRebuild:
    @staticmethod
    def _schema(source_type: str = "Postgres") -> MagicMock:
        schema = MagicMock()
        schema.source.source_type = source_type
        return schema

    @parameterized.expand(
        [
            ("full_refresh", {"sync_type": "full_refresh"}, None, None, True),
            ("first_sync_incremental", {"is_first_ever_sync": True}, None, None, True),
            ("first_sync_append", {"sync_type": "append", "is_first_ever_sync": True}, None, None, True),
            ("incremental_on_an_existing_table", {}, None, None, False),
            ("append_on_an_existing_table", {"sync_type": "append"}, None, None, False),
            ("cdc", {"is_first_ever_sync": True, "cdc_write_mode": "upsert"}, None, None, False),
            ("partial_data_loading", {"is_first_ever_sync": True}, ExternalDataSourceType.STRIPE, None, False),
            ("set_spanning_two_runs", {"sync_type": "full_refresh"}, None, [("run-0", 9), ("run-1", 10)], False),
            (
                "set_crossing_a_check",
                {"sync_type": "full_refresh", "batch_index": 9},
                None,
                [("run-1", 9), ("run-1", 10)],
                True,
            ),
            ("between_checks", {"sync_type": "full_refresh", "batch_index": 11}, None, None, False),
            ("first_batch", {"sync_type": "full_refresh", "batch_index": 0}, None, None, False),
        ]
    )
    def test_which_writes_check_for_compaction(
        self,
        _name: str,
        overrides: dict[str, Any],
        source_type: str | None,
        members: list[tuple[str, int]] | None,
        expected: bool,
    ) -> None:
        signal = ExportSignalMessage.from_dict(_message(**{"batch_index": 10, **overrides}))
        members = members or [(signal.run_uuid, signal.batch_index)]
        with patch(f"{_PROCESSOR}.is_schema_flag_enabled", return_value=True):
            assert _rebuild_compaction_due(signal, self._schema(source_type or "Postgres"), members) is expected

    def test_the_flag_turns_it_off(self) -> None:
        signal = ExportSignalMessage.from_dict(_message(batch_index=10, sync_type="full_refresh"))
        with patch(f"{_PROCESSOR}.is_schema_flag_enabled", return_value=False):
            assert _rebuild_compaction_due(signal, self._schema(), [(signal.run_uuid, 10)]) is False

    def _load(self, table_path: str, sync_type: str, first_index: int, *, enabled: bool) -> None:
        write_deltalake(table_path, TestTableHandleReuse._SEED)
        with (
            override_settings(DATA_WAREHOUSE_REBUILD_COMPACT_MIN_REMOVABLE_FILES=3),
            patch(f"{_PROCESSOR}.REBUILD_COMPACT_CHECK_EVERY", 5),
            TestTableHandleReuse()._loader(table_path, []),
            patch(f"{_PROCESSOR}.is_schema_flag_enabled", return_value=enabled),
        ):
            for index in range(first_index, first_index + 12):
                process_message(TestTableHandleReuse._batch(index, sync_type=sync_type))

    @parameterized.expand(
        [
            ("rebuild_run_compacts_as_it_loads", "full_refresh", 0, True),
            ("append_on_an_existing_table_waits_for_post_load", "append", 1, False),
        ]
    )
    def test_compaction_between_batches_keeps_the_rows(
        self, _name: str, sync_type: str, first_index: int, compacts: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            on_path, off_path = f"{tmp}/on", f"{tmp}/off"
            self._load(on_path, sync_type, first_index, enabled=True)
            self._load(off_path, sync_type, first_index, enabled=False)

            on_table, off_table = DeltaTable(on_path), DeltaTable(off_path)
            assert (
                on_table.to_pyarrow_table().sort_by([("id", "ascending"), ("name", "ascending")]).to_pydict()
                == off_table.to_pyarrow_table().sort_by([("id", "ascending"), ("name", "ascending")]).to_pydict()
            )
            assert (len(on_table.file_uris()) < len(off_table.file_uris())) is compacts
