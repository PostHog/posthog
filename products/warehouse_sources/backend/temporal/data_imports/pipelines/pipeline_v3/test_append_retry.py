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
_CONFIG_WRITE = "products.warehouse_sources.backend.models.external_data_schema.update_sync_type_config_keys"


def _schema(*, sync_type: str = "append", last_value: Any = 500) -> ExternalDataSchema:
    config: dict[str, Any] = {"incremental_field": "id", "incremental_field_type": IncrementalFieldType.Integer}
    if last_value is not None:
        config["incremental_field_last_value"] = last_value
    return ExternalDataSchema(name="events", sync_type=sync_type, sync_type_config=config)


def _apply_in_memory(schema: ExternalDataSchema):
    def apply(schema_id: Any, team_id: Any, *, mutate: Any, **_: Any) -> dict[str, Any]:
        mutate(schema.sync_type_config)
        return schema.sync_type_config

    return patch(_CONFIG_WRITE, side_effect=apply)


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

        head, tail = split_trailing_cursor_ties(table, "id")

        assert head["id"].to_pylist() == kept
        assert tail["id"].to_pylist() == held
        assert head.num_rows + tail.num_rows == table.num_rows


class TestSettleAppendRetry:
    @pytest.mark.parametrize("watermark,expected_watermark", [(500, 3_000), (None, 3_000), (5_000, 5_000)])
    def test_fences_earlier_attempts_waits_for_loads_then_commits_the_loaded_cursor(
        self, watermark: Any, expected_watermark: Any
    ) -> None:
        schema = _schema(last_value=watermark)
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
            _apply_in_memory(schema),
        ):
            loaded_rows = _settle(schema, sleep=sleep)

        assert loaded_rows == 250
        assert schema.sync_type_config["incremental_field_last_value"] == expected_watermark
        assert fence.call_args.kwargs["run_uuids"] == ["wfrun-1-a1", "wfrun-1-a2"]
        assert settle.call_args.kwargs == {"job_id": "job-1", "current_run_uuid": "wfrun-1-a3"}
        sleep.assert_called_once_with(1)

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
    def test_keeps_the_watermark_when_no_loaded_cursor_is_known(
        self, settled: EarlierAttempts, expected: int | None
    ) -> None:
        schema = _schema()
        with patch(f"{_QUEUE}.fence_runs"), patch(f"{_QUEUE}.settle_earlier_attempts", return_value=settled):
            with _apply_in_memory(schema):
                assert _settle(schema) == expected

        assert schema.sync_type_config["incremental_field_last_value"] == 500

    def test_gives_up_when_a_batch_stays_loading(self) -> None:
        schema = _schema()
        still_loading = EarlierAttempts(unsettled_batches=1, loaded_rows=150, loaded_last_value=2_000)
        with (
            patch(f"{_QUEUE}.fence_runs"),
            patch(f"{_QUEUE}.settle_earlier_attempts", return_value=still_loading),
            _apply_in_memory(schema),
        ):
            with pytest.raises(TimeoutError):
                _settle(schema)

        assert schema.sync_type_config["incremental_field_last_value"] == 500
