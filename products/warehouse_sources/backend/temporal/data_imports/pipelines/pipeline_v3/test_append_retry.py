from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry import (
    settle_append_retry,
    split_trailing_cursor_ties,
)
from products.warehouse_sources.backend.types import IncrementalFieldType
from products.warehouse_sources_queue.backend.core.jobs_db import EarlierAttempts

_QUEUE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry.BatchQueue"


def _schema(*, sync_type: str = "append") -> ExternalDataSchema:
    config: dict[str, Any] = {
        "incremental_field": "id",
        "incremental_field_type": IncrementalFieldType.Integer,
        "incremental_field_last_value": 500,
    }
    return ExternalDataSchema(name="events", sync_type=sync_type, sync_type_config=config)


def _settle(schema: ExternalDataSchema, sleep: MagicMock | None = None, **overrides: Any) -> int | None:
    kwargs: dict[str, Any] = {
        "team_id": 1,
        "source_id": "source-1",
        "job_id": "job-1",
        "workflow_run_id": "wfrun-1",
        "attempt": 3,
        "rows_ordered_by_cursor": True,
        "connect": MagicMock(),
        "sleep": sleep or MagicMock(),
        "poll_seconds": 1,
        "timeout_seconds": 3,
        **overrides,
    }
    return settle_append_retry(schema, **kwargs)


class TestSplitTrailingCursorTies:
    @pytest.mark.parametrize(
        "ids,kept,held",
        [
            ([1, 2, 2], [1], [2, 2]),
            ([1, 2, 3], [1, 2], [3]),
            ([4, 4, 4], [], [4, 4, 4]),
        ],
    )
    def test_holds_back_every_row_that_shares_the_highest_cursor(
        self, ids: list[int], kept: list[int], held: list[int]
    ) -> None:
        table = pa.table({"id": pa.array(ids, pa.int64()), "value": pa.array(range(len(ids)), pa.int64())})

        split = split_trailing_cursor_ties(table, "id")

        assert split.kept["id"].to_pylist() == kept
        assert split.held["id"].to_pylist() == held
        assert split.kept.num_rows + split.held.num_rows == table.num_rows


class TestSettleAppendRetry:
    def test_fences_earlier_attempts_waits_for_loads_then_reloads_the_watermark(self) -> None:
        schema = _schema()
        sleep = MagicMock()
        with (
            patch(f"{_QUEUE}.fence_runs") as fence,
            patch(
                f"{_QUEUE}.settle_earlier_attempts",
                side_effect=[
                    EarlierAttempts(unsettled_batches=1, loaded_rows=150, loaded_last_value=2_000),
                    EarlierAttempts(unsettled_batches=0, loaded_rows=250, loaded_last_value=3_000),
                ],
            ) as settle,
            patch.object(schema, "refresh_from_db") as refresh,
        ):
            loaded_rows = _settle(schema, sleep=sleep)

        assert loaded_rows == 250
        assert fence.call_args.kwargs["run_uuids"] == ["wfrun-1-a1", "wfrun-1-a2"]
        assert settle.call_args.kwargs == {"job_id": "job-1", "current_run_uuid": "wfrun-1-a3"}
        sleep.assert_called_once_with(1)
        refresh.assert_called_once_with(fields=["sync_type_config"])

    @pytest.mark.parametrize(
        "overrides,sync_type",
        [
            ({"attempt": 1}, "append"),
            ({"rows_ordered_by_cursor": False}, "append"),
            ({"workflow_run_id": None}, "append"),
            ({}, "incremental"),
            ({}, "full_refresh"),
        ],
    )
    def test_leaves_runs_it_does_not_apply_to_alone(self, overrides: dict[str, Any], sync_type: str) -> None:
        schema = _schema(sync_type=sync_type)
        with patch(f"{_QUEUE}.fence_runs") as fence, patch(f"{_QUEUE}.settle_earlier_attempts") as settle:
            assert _settle(schema, **overrides) is None

        fence.assert_not_called()
        settle.assert_not_called()

    @pytest.mark.parametrize(
        "settled,expected",
        [
            (EarlierAttempts(unsettled_batches=0, loaded_rows=0, loaded_last_value=None), 0),
            (EarlierAttempts(unsettled_batches=0, loaded_rows=90, loaded_last_value=None), None),
        ],
    )
    def test_reads_again_rows_loaded_without_a_cursor(self, settled: EarlierAttempts, expected: int | None) -> None:
        schema = _schema()
        with (
            patch(f"{_QUEUE}.fence_runs"),
            patch(f"{_QUEUE}.settle_earlier_attempts", return_value=settled),
            patch.object(schema, "refresh_from_db"),
        ):
            assert _settle(schema) == expected

    def test_gives_up_when_a_batch_stays_loading(self) -> None:
        schema = _schema()
        still_loading = EarlierAttempts(unsettled_batches=1, loaded_rows=150, loaded_last_value=2_000)
        with patch(f"{_QUEUE}.fence_runs"), patch(f"{_QUEUE}.settle_earlier_attempts", return_value=still_loading):
            with pytest.raises(TimeoutError):
                _settle(schema)
