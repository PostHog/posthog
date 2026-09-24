import pytest
from unittest.mock import MagicMock

from django.test import override_settings

import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_MERGE_CONFLICT_RETRIES,
    ObjectStorePermissionDeniedError,
    delta_merge_spill_kwargs,
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger


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
    `compact_table`'s optimize.compact."""

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
