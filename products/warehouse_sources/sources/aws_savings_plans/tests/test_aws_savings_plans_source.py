import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.source import (
    AwsSavingsPlansSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)


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
    config = AwsSavingsPlansSourceConfig(
        aws_access_key_id="example", aws_secret_access_key="secret", start_date="2025-01-01"
    )
    with time_machine.travel("2025-01-12", tick=False):
        result = SourceDriver(AwsSavingsPlansSource(), config).run(
            name,
            [ScriptedResponse(json={})],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value="2025-01-10",
        )
    assert result.raised is None
    assert result.rows == []
    assert result.requests[0].json().get("TimePeriod", {}).get("Start") == start
    assert result.response is not None
    assert result.response.partition_keys == partition
    assert result.response.sort_mode == "desc"
