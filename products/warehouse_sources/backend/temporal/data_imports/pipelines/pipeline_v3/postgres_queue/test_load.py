from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.load import (
    process_batch,
)

_LOAD_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.load"


def _make_batch(**overrides: Any) -> PendingBatch:
    defaults: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "team_id": 1,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "job_id": "job-1",
        "run_uuid": "run-1",
        "batch_index": 0,
        "s3_path": "s3://bucket/path",
        "row_count": 100,
        "byte_size": 1024,
        "is_final_batch": False,
        "total_batches": None,
        "total_rows": None,
        "sync_type": "full_refresh",
        "cumulative_row_count": 0,
        "resource_name": "test_resource",
        "is_resume": False,
        "is_first_ever_sync": False,
        "metadata": {},
        "latest_attempt": 0,
    }
    defaults.update(overrides)
    return PendingBatch(**defaults)


class TestProcessBatch:
    @parameterized.expand(
        [
            ("never_delivered", 0, 1),
            ("one_prior_attempt", 1, 2),
            ("several_prior_attempts", 4, 5),
        ]
    )
    @pytest.mark.asyncio
    async def test_forwards_attempt_number(self, _name: str, latest_attempt: int, expected_attempt: int):
        # An off-by-one here reads a redelivery as a first delivery, which lets the processor skip
        # the delta-history idempotency scan and re-write a batch a crashed attempt already committed.
        with patch(f"{_LOAD_MODULE}.process_message") as mock_process_message:
            await process_batch(_make_batch(latest_attempt=latest_attempt))

        assert mock_process_message.call_args.kwargs["attempt"] == expected_attempt
