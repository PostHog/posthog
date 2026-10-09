import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.source import (
    AwsSavingsPlansSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.aws_savings_plans"


@pytest.mark.parametrize(
    "name,incremental,start,partition",
    [
        ("savings_plans", False, None, None),
        ("coverage_daily", True, "2025-01-03", ["period_start"]),
        ("utilization_daily", False, "2025-01-01", ["period_start"]),
    ],
)
def test_pipeline_passes_cursor_and_partition_settings(
    name: str, incremental: bool, start: str | None, partition: list[str] | None
) -> None:
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = name
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = "2025-01-10"
    inputs.api_version = None
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    config = AwsSavingsPlansSourceConfig(
        aws_access_key_id="example", aws_secret_access_key="secret", start_date="2025-01-01"
    )
    response = requests.Response()
    response.status_code = 200
    response._content = b"{}"
    with time_machine.travel("2025-01-12", tick=False), patch(f"{MODULE}.make_tracked_session") as factory:
        factory.return_value.post.return_value = response
        result = AwsSavingsPlansSource().source_for_pipeline(config, manager, inputs)
        assert list(cast(Iterable[Any], result.items())) == []
        payload = json.loads(factory.return_value.post.call_args.kwargs["data"])
    assert payload.get("TimePeriod", {}).get("Start") == start
    assert result.partition_keys == partition
    assert result.sort_mode == "desc"
