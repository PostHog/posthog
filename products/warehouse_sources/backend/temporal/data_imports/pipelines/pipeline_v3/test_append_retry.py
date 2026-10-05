from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_schema import WATERMARK_JOB_KEY, ExternalDataSchema
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


def _settle(schema: ExternalDataSchema, **overrides: Any) -> int | None:
    kwargs: dict[str, Any] = {
        "team_id": 1,
        "source_id": "source-1",
        "job_id": "job-1",
        "workflow_run_id": "wfrun-1",
        "attempt": 3,
        "rows_ordered_by_cursor": True,
        "connect": MagicMock(),
        **overrides,
    }
    return settle_append_retry(schema, **kwargs)


def _stored_watermark(schema: ExternalDataSchema, last_value: int, job_id: str) -> Any:
    def refresh(**_: Any) -> None:
        schema.sync_type_config = {
            **schema.sync_type_config,
            "incremental_field_last_value": last_value,
            WATERMARK_JOB_KEY: job_id,
        }

    return patch.object(schema, "refresh_from_db", side_effect=refresh)


class TestSplitTrailingCursorTies:
    @pytest.mark.parametrize(
        "ids,kept,held",
        [
            ([1, 2, 2], [1], [2, 2]),
            ([1, 2, 3], [1, 2], [3]),
            ([4, 4, 4], [], [4, 4, 4]),
            ([1, 2, None], [1], [2, None]),
            ([None, None], [None, None], []),
        ],
    )
    def test_holds_back_every_row_that_shares_the_highest_cursor(
        self, ids: list[int | None], kept: list[int | None], held: list[int | None]
    ) -> None:
        table = pa.table({"id": pa.array(ids, pa.int64()), "value": pa.array(range(len(ids)), pa.int64())})

        split = split_trailing_cursor_ties(table, "id")

        assert split.kept["id"].to_pylist() == kept
        assert split.held["id"].to_pylist() == held
        assert split.kept.num_rows + split.held.num_rows == table.num_rows


class TestSettleAppendRetry:
    def test_fences_earlier_attempts_then_resumes_after_the_rows_this_job_loaded(self) -> None:
        schema = _schema()
        with (
            patch(f"{_QUEUE}.fence_runs") as fence,
            patch(
                f"{_QUEUE}.settle_earlier_attempts",
                return_value=EarlierAttempts(loaded_rows=250, loaded_last_value=3_000),
            ) as settle,
            _stored_watermark(schema, 3_000, "job-1"),
        ):
            assert _settle(schema) == 250

        assert fence.call_args.kwargs["run_uuids"] == ["wfrun-1-a1", "wfrun-1-a2"]
        assert settle.call_args.kwargs == {"job_id": "job-1", "current_run_uuid": "wfrun-1-a3"}

    @pytest.mark.parametrize(
        "loaded,stored_value,stored_job",
        [
            (EarlierAttempts(loaded_rows=0, loaded_last_value=None), 500, "job-0"),
            (EarlierAttempts(loaded_rows=90, loaded_last_value=None), 500, "job-0"),
            (EarlierAttempts(loaded_rows=90, loaded_last_value=3_000), 3_000, "job-0"),
            (EarlierAttempts(loaded_rows=90, loaded_last_value=3_000), 2_000, "job-1"),
        ],
    )
    def test_reads_as_before_unless_this_job_committed_the_loaded_cursor(
        self, loaded: EarlierAttempts, stored_value: int, stored_job: str
    ) -> None:
        schema = _schema()
        with (
            patch(f"{_QUEUE}.fence_runs"),
            patch(f"{_QUEUE}.settle_earlier_attempts", return_value=loaded),
            _stored_watermark(schema, stored_value, stored_job),
        ):
            assert _settle(schema) is None

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
