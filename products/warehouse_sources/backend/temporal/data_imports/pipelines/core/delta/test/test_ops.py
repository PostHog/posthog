import pytest
from unittest.mock import MagicMock

from django.test import override_settings

import pyarrow as pa
import deltalake
import botocore.exceptions
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_MERGE_CONFLICT_RETRIES,
    ObjectStorePermissionDeniedError,
    delta_merge_spill_kwargs,
    execute_with_conflict_retry,
    wide_row_target_file_size,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger


def _permission_error_with_client_error_cause() -> PermissionError:
    # Mirrors s3fs.errors.translate_boto_error: the message on the PermissionError it raises is the
    # server's own (here generic) Message, while the original ClientError (which carries the real
    # Code) is kept only as __cause__.
    client_error = botocore.exceptions.ClientError(
        {"Error": {"Code": "SignatureDoesNotMatch", "Message": "Invalid argument."}}, "PutObject"
    )
    permission_error = PermissionError("Invalid argument.")
    permission_error.__cause__ = client_error
    return permission_error


_KiB = 1024
_MiB = 1024 * 1024


def _add_actions(files: list[tuple[int, int | None]]) -> pa.Table:
    return pa.table(
        {
            "size_bytes": pa.array([size for size, _ in files], pa.int64()),
            "num_records": pa.array([rows for _, rows in files], pa.int64()),
        }
    )


class TestWideRowTargetFileSize:
    @parameterized.expand(
        [
            ("empty_table", [], None),
            ("narrow_rows", [(64 * _MiB, 64 * 1024)], None),
            ("just_under_the_wide_threshold", [(64 * _MiB, 64 * _MiB // (8 * _KiB - 1))], None),
            # 1,024 rows of 8 KiB is 8 MiB, which the lower bound raises to 16 MiB.
            ("wide_threshold_clamps_to_the_lower_bound", [(64 * _MiB, 64 * _MiB // (8 * _KiB))], 16 * _MiB),
            ("inside_the_band", [(100 * _MiB, 100 * _MiB // (20 * _KiB))], 20 * _MiB),
            ("very_wide_rows_clamp_to_the_upper_bound", [(100 * _MiB, 100 * _MiB // (100 * _KiB))], 32 * _MiB),
            # Bytes per row come from the whole table, not from the largest file.
            ("weighted_over_files", [(80 * _MiB, 80 * _MiB // (40 * _KiB)), (20 * _MiB, 20 * 1024)], None),
            ("small_wide_table_waits", [(31 * _MiB, 31 * _MiB // (100 * _KiB))], None),
            # A file without a row count says nothing about bytes per row, so it does not count.
            (
                "files_without_row_counts_are_skipped",
                [(100 * _MiB, 100 * _MiB // (20 * _KiB)), (500 * _MiB, None)],
                20 * _MiB,
            ),
            ("no_file_records_its_rows", [(100 * _MiB, None)], None),
            ("rounds_to_whole_mib", [(100 * _MiB, round(100 * _MiB / (20.3 * _KiB)))], 20 * _MiB),
        ]
    )
    def test_target(self, _name: str, files: list[tuple[int, int | None]], expected: int | None) -> None:
        assert wide_row_target_file_size(_add_actions(files)) == expected

    def test_add_actions_without_row_counts(self) -> None:
        assert wide_row_target_file_size(pa.table({"size_bytes": pa.array([100 * _MiB], pa.int64())})) is None


class TestDeltaMergeSpillKwargs:
    # Guards the wiring from settings → delta-rs merge kwargs. A silent break here (renamed setting,
    # dropped forwarding, or emitting a None kwarg) stops merges spilling to disk and OOMs return.
    @parameterized.expand(
        [
            ("both_unset", None, None, {}),
            ("only_spill", 6_442_450_944, None, {"max_spill_size": 6_442_450_944}),
            ("only_temp_dir", None, 51_539_607_552, {"max_temp_directory_size": 51_539_607_552}),
            (
                "both_set",
                6_442_450_944,
                51_539_607_552,
                {"max_spill_size": 6_442_450_944, "max_temp_directory_size": 51_539_607_552},
            ),
        ]
    )
    def test_kwargs_from_settings(
        self, _case: str, spill: int | None, temp_dir: int | None, expected: dict[str, int]
    ) -> None:
        with override_settings(
            DATA_WAREHOUSE_DELTA_MERGE_MAX_SPILL_SIZE_BYTES=spill,
            DATA_WAREHOUSE_DELTA_MERGE_MAX_TEMP_DIRECTORY_SIZE_BYTES=temp_dir,
        ):
            assert delta_merge_spill_kwargs() == expected


class TestExecuteWithConflictRetry:
    """A committing operation's CommitFailedError means delta-rs's conflict checker rejected the
    commit outright, without spending any of its own internal retry budget (see the comment on
    DELTA_MERGE_CONFLICT_RETRIES). Regression coverage for the sync dying on the first such
    conflict instead of refreshing the table and re-running the operation, as the error's own
    "must be rerun" message calls for. Shared by merges, overwrite/append writes, and
    `compact_if_fragmented`'s optimize.compact."""

    @pytest.mark.asyncio
    async def test_succeeds_without_retry(self):
        table = MagicMock()
        operation_fn = MagicMock(return_value={"num_output_rows": 1})

        result = await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert result == {"num_output_rows": 1}
        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_conflict_then_succeeds(self):
        table = MagicMock()
        operation_fn = MagicMock(
            side_effect=[
                deltalake.exceptions.CommitFailedError("Commit failed: a concurrent transactions added new data."),
                {"num_output_rows": 1},
            ]
        )

        result = await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert result == {"num_output_rows": 1}
        assert operation_fn.call_count == 2
        table.update_incremental.assert_called_once()

    @pytest.mark.asyncio
    async def test_can_propagate_a_conflict_without_retrying(self):
        table = MagicMock()
        operation_fn = MagicMock(
            side_effect=deltalake.exceptions.CommitFailedError(
                "Commit failed: a concurrent transaction added new data."
            )
        )

        with pytest.raises(deltalake.exceptions.CommitFailedError):
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger(), conflict_retries=0)

        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_invalid_version_race_then_succeeds(self):
        # Two writers racing to commit the very first version of a brand-new table surface as a
        # plain DeltaError, not CommitFailedError (delta-rs's Python binding only special-cases
        # DeltaTableError::Transaction — see errors.py's is_invalid_version_race). Regression
        # coverage for this race killing the sync instead of retrying like a normal commit conflict.
        table = MagicMock()
        operation_fn = MagicMock(
            side_effect=[
                deltalake.exceptions.DeltaError("Invalid table version: 0"),
                {"num_output_rows": 1},
            ]
        )

        result = await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert result == {"num_output_rows": 1}
        assert operation_fn.call_count == 2
        table.update_incremental.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_missing_scan_file_race_then_succeeds(self):
        # A merge plans its scan against the stale file list on the handle it was given; if a
        # concurrent vacuum (e.g. a zombie attempt's post-load pass) deletes one of those files
        # before the scan reads it, delta-rs surfaces a 404 as a generic DeltaError with no typed
        # class to catch (see errors.py's is_missing_scan_file_race). Regression coverage for this
        # race killing the sync instead of refreshing the table and retrying like a commit conflict.
        table = MagicMock()
        operation_fn = MagicMock(
            side_effect=[
                deltalake.exceptions.DeltaError(
                    "Generic DeltaTable error: Parquet error: Parquet error: Failed to fetch metadata "
                    "for file dlt/team_1_source_1/orders/part-00000-abc.snappy.parquet: Object Store "
                    "error: Object at location dlt/team_1_source_1/orders/part-00000-abc.snappy.parquet "
                    "not found: Error performing GET in 20ms - Server returned non-2xx status code: "
                    "404 Not Found"
                ),
                {"num_output_rows": 1},
            ]
        )

        result = await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert result == {"num_output_rows": 1}
        assert operation_fn.call_count == 2
        table.update_incremental.assert_called_once()

    @pytest.mark.asyncio
    async def test_unrelated_delta_error_propagates_without_retry(self):
        table = MagicMock()
        operation_fn = MagicMock(side_effect=deltalake.exceptions.DeltaError("no protocol found in delta log"))

        with pytest.raises(deltalake.exceptions.DeltaError):
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()

    @pytest.mark.asyncio
    async def test_gives_up_after_exhausting_retries(self):
        table = MagicMock()
        operation_fn = MagicMock(
            side_effect=deltalake.exceptions.CommitFailedError(
                "Commit failed: a concurrent transactions added new data."
            )
        )

        with pytest.raises(deltalake.exceptions.CommitFailedError):
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert operation_fn.call_count == DELTA_MERGE_CONFLICT_RETRIES + 1
        assert table.update_incremental.call_count == DELTA_MERGE_CONFLICT_RETRIES

    @pytest.mark.asyncio
    async def test_other_errors_propagate_without_retry(self):
        table = MagicMock()
        operation_fn = MagicMock(side_effect=ValueError("not a commit conflict"))

        with pytest.raises(ValueError):
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_object_store_error_is_wrapped_and_not_retried(self):
        # delta-rs prefixes a self-recovering object-store blip (e.g. the backend refusing a PUT
        # because it's temporarily out of free space) with "Generic S3 error". Regression coverage
        # for this reaching the caller as a raw DeltaError, which the activity boundary would report
        # as a fresh error-tracking issue per write and would leak into the customer-facing error,
        # instead of the same non-reportable classification get_delta_table already applies.
        table = MagicMock()
        error = deltalake.exceptions.DeltaError(
            "Failed to parse parquet: External: Generic S3 error: Error performing PUT "
            "in 5s, after 10 retries - Server returned non-2xx status code: 507 Insufficient Storage"
        )
        operation_fn = MagicMock(side_effect=error)

        with pytest.raises(TransientObjectStoreError) as exc_info:
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert exc_info.value.__cause__ is error
        # This can reach the customer as the sync run's error text if every retry is exhausted, so
        # the raw storage text (which can name the bucket and the object key) must not survive into
        # the wrapper's own message - only onto __cause__, asserted above.
        assert "Insufficient Storage" not in str(exc_info.value)
        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()

    @parameterized.expand(
        [
            # delta-rs maps a 403 from its Rust object_store crate onto io::ErrorKind::PermissionDenied
            # and hands the fixed sentence back as a bare OSError.
            (
                "kernel_privileges_oserror",
                OSError(
                    "Kernel error -> The operation lacked the necessary privileges to complete for path "
                    "warehouse/team_42_source_7/orders/part-00003.parquet"
                ),
            ),
            # The same refusal during the commit itself arrives as CommitFailedError, because delta-rs
            # maps every DeltaTableError::Transaction onto that class whatever the transaction failed on.
            # Without classifying the text first, this reads as a conflict and spends the whole budget.
            (
                "refusal_wrapped_in_commit_failed",
                deltalake.exceptions.CommitFailedError(
                    "Object store error: Generic S3 error: The operation lacked the necessary privileges "
                    "to complete for path warehouse/team_42_source_7/orders/_delta_log/00000000000000000012.json"
                ),
            ),
            # s3fs translates an explicit S3 AccessDenied response code into PermissionError.
            ("s3fs_access_denied", PermissionError("Access Denied")),
            # s3fs collapses InvalidAccessKeyId (the worker's own access key no longer exists) into
            # the same PermissionError type, with AWS's own fixed message instead of "Access Denied".
            (
                "s3fs_invalid_access_key_id",
                PermissionError("The AWS Access Key Id you provided does not exist in our records."),
            ),
            # s3fs also collapses SignatureDoesNotMatch into PermissionError, but our backend returns
            # a generic "Invalid argument." Message for it instead of AWS's usual signature-mismatch
            # sentence, so none of the message needles above match it. Regression coverage for this
            # refusal leaking as a raw, unclassified PermissionError instead of being read off the
            # chained ClientError's actual code.
            ("s3fs_signature_does_not_match", _permission_error_with_client_error_cause()),
        ]
    )
    @pytest.mark.asyncio
    async def test_object_store_refusal_is_typed_and_not_retried(self, _case: str, error: Exception):
        # A refused read, write or delete is not a race, so re-running the operation against a
        # refreshed table makes the same refused calls. Regression coverage for the refusal reaching
        # the caller as a raw OSError (which no retry budget in this package classifies) and for a
        # refusal wrapped in CommitFailedError burning the conflict budget before it does.
        table = MagicMock()
        operation_fn = MagicMock(side_effect=error)

        with pytest.raises(ObjectStorePermissionDeniedError) as exc_info:
            await execute_with_conflict_retry(table, operation_fn, "op", make_logger())

        assert exc_info.value.__cause__ is error
        # The message reaches the customer as the sync run's error text, so the object key the raw
        # error names must not survive into it.
        assert "warehouse/" not in str(exc_info.value)
        # It also reaches every source's non-retryable-error patterns (see external_data_job.py),
        # many of which match "access denied". A message carrying that phrase pauses the schema and
        # tells the customer to go fix credentials that are working.
        assert "access denied" not in str(exc_info.value).lower()
        operation_fn.assert_called_once()
        table.update_incremental.assert_not_called()
