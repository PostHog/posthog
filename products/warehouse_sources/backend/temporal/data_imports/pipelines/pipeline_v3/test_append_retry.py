from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry import (
    resume_append_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    EarlierAttempts,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_SETTLE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.append_retry.BatchQueue.settle_earlier_attempts"
_CONFIG_WRITE = "products.warehouse_sources.backend.models.external_data_schema.update_sync_type_config_keys"


def _schema(*, sync_type: str = "append", last_value: Any = 500) -> ExternalDataSchema:
    config: dict[str, Any] = {"incremental_field": "id", "incremental_field_type": IncrementalFieldType.Integer}
    if last_value is not None:
        config["incremental_field_last_value"] = last_value
    return ExternalDataSchema(sync_type=sync_type, sync_type_config=config)


def _apply_in_memory(schema: ExternalDataSchema):
    def apply(schema_id: Any, team_id: Any, *, mutate: Any, **_: Any) -> dict[str, Any]:
        mutate(schema.sync_type_config)
        return schema.sync_type_config

    return patch(_CONFIG_WRITE, side_effect=apply)


def _resume(schema: ExternalDataSchema, sleep: MagicMock | None = None, **overrides: Any) -> int | None:
    kwargs: dict[str, Any] = {
        "job_id": "job-1",
        "workflow_run_id": "wfrun-1",
        "attempt": 2,
        "source_is_resumable": False,
        "connect": MagicMock(),
        "sleep": sleep or MagicMock(),
        "poll_seconds": 1,
        "timeout_seconds": 3,
        **overrides,
    }
    return resume_append_retry(schema, **kwargs)


class TestResumeAppendRetry:
    @pytest.mark.parametrize("watermark,expected_watermark", [(500, 3_000), (None, 3_000), (5_000, 5_000)])
    def test_resumes_after_the_last_loaded_batch_once_no_batch_is_loading(
        self, watermark: Any, expected_watermark: Any
    ) -> None:
        schema = _schema(last_value=watermark)
        sleep = MagicMock()
        with (
            patch(
                _SETTLE,
                side_effect=[
                    EarlierAttempts(unsettled_batches=1, loaded_rows=150, loaded_last_value=2_000),
                    EarlierAttempts(unsettled_batches=0, loaded_rows=250, loaded_last_value=3_000),
                ],
            ) as settle,
            _apply_in_memory(schema),
        ):
            loaded_rows = _resume(schema, sleep=sleep)

        assert loaded_rows == 250
        assert schema.sync_type_config["incremental_field_last_value"] == expected_watermark
        assert settle.call_args.kwargs == {"job_id": "job-1", "current_run_uuid": "wfrun-1-a2"}
        sleep.assert_called_once_with(1)

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
        schema = _schema(sync_type=sync_type)
        with patch(_SETTLE) as settle, _apply_in_memory(schema):
            assert _resume(schema, **overrides) is None

        settle.assert_not_called()
        assert schema.sync_type_config["incremental_field_last_value"] == 500

    @pytest.mark.parametrize("loaded_rows", [0, 90])
    def test_restarts_from_the_watermark_when_no_loaded_cursor_is_known(self, loaded_rows: int) -> None:
        settled = EarlierAttempts(unsettled_batches=0, loaded_rows=loaded_rows, loaded_last_value=None)
        schema = _schema()
        with patch(_SETTLE, return_value=settled), _apply_in_memory(schema):
            assert _resume(schema) is None

        assert schema.sync_type_config["incremental_field_last_value"] == 500

    def test_gives_up_when_a_batch_stays_loading(self) -> None:
        schema = _schema()
        still_loading = EarlierAttempts(unsettled_batches=1, loaded_rows=150, loaded_last_value=2_000)
        with patch(_SETTLE, return_value=still_loading), _apply_in_memory(schema):
            with pytest.raises(TimeoutError):
                _resume(schema)

        assert schema.sync_type_config["incremental_field_last_value"] == 500
