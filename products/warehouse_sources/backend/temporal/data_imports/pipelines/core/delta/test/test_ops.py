import pytest
from unittest.mock import MagicMock

from django.test import override_settings

import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_MERGE_CONFLICT_RETRIES,
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
