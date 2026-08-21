from collections.abc import Iterable
from typing import Any, cast

from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer import (
    aws_cost_explorer as transport_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.source import (
    AwsCostExplorerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostexplorer import (
    AwsCostExplorerSourceConfig,
)


def make_inputs(
    schema_name: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="period_start",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsCostExplorerSource:
    def setup_method(self) -> None:
        self.source = AwsCostExplorerSource()
        self.config = AwsCostExplorerSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
            start_date="2024-01-01",
        )

    def test_items_are_lazy_so_building_the_response_bills_no_api_request(self) -> None:
        inputs = make_inputs("cost_and_usage_daily")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_operation") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
