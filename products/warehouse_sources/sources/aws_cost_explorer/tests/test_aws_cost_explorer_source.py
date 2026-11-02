import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer import (
    aws_cost_explorer as transport_module,
    source as source_module,
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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AWS Cost Explorer request failed: LimitExceededException - Rate exceeded",
            "AWS Cost Explorer request failed: HTTP 503 - ",
            "AWS Cost Explorer request failed: InternalFailure - ",
            "AWS Cost Explorer request failed: ServiceUnavailableException - ",
        ],
    )
    def test_transient_aws_failures_keep_retrying(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())
        assert any(key in observed_error for key in self.source.get_retryable_errors())

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2024, 5, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_cost_explorer_source") as build:
            inputs = make_inputs("cost_and_usage_daily", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("cost_and_usage_daily", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None
            assert build.call_args[1]["start_date"] == "2024-01-01"

    def test_items_are_lazy_so_building_the_response_bills_no_api_request(self) -> None:
        inputs = make_inputs("cost_and_usage_daily")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_operation") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
