from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry import (
    find_append_retry_resume,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    EarlierBatch,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_NEWEST = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry.BatchQueue.newest_batch_of_earlier_attempts"


def _earlier_batch(incremental_last_value: Any = 2_000) -> EarlierBatch:
    return EarlierBatch(
        id="batch-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        run_uuid="wfrun-1-a1",
        batch_index=4,
        is_final_batch=False,
        incremental_last_value=incremental_last_value,
    )


def _find(sync_type: str = "append", **overrides: Any) -> EarlierBatch | None:
    schema = ExternalDataSchema(
        sync_type=sync_type,
        sync_type_config={"incremental_field": "id", "incremental_field_type": IncrementalFieldType.Integer},
    )
    kwargs: dict[str, Any] = {
        "job_id": "job-1",
        "workflow_run_id": "wfrun-1",
        "attempt": 2,
        "source_is_resumable": False,
        "connect": MagicMock(),
        **overrides,
    }
    return find_append_retry_resume(schema, **kwargs)


class TestFindAppendRetryResume:
    def test_resumes_after_the_newest_batch_an_earlier_attempt_queued(self) -> None:
        earlier = _earlier_batch()
        with patch(_NEWEST, return_value=earlier) as newest:
            assert _find() == earlier

        assert newest.call_args.kwargs == {"job_id": "job-1", "current_run_uuid": "wfrun-1-a2"}

    @pytest.mark.parametrize(
        "overrides,sync_type",
        [
            ({"attempt": 1}, "append"),
            ({"source_is_resumable": True}, "append"),
            ({"workflow_run_id": None}, "append"),
            ({}, "incremental"),
            ({}, "full_refresh"),
        ],
    )
    def test_leaves_runs_it_does_not_apply_to_alone(self, overrides: dict[str, Any], sync_type: str) -> None:
        with patch(_NEWEST) as newest:
            assert _find(sync_type, **overrides) is None

        newest.assert_not_called()

    @pytest.mark.parametrize("earlier", [None, _earlier_batch(incremental_last_value=None)])
    def test_restarts_from_the_watermark_without_a_queued_cursor(self, earlier: EarlierBatch | None) -> None:
        with patch(_NEWEST, return_value=earlier):
            assert _find() is None
