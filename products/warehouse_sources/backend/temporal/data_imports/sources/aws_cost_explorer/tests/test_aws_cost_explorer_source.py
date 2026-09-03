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
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.settings import (
    AWS_COST_EXPLORER_ENDPOINTS,
    ENDPOINTS,
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
            "AWS Cost Explorer request failed: AccessDeniedException - User is not authorized to perform ce:GetCostAndUsage",
            "AWS Cost Explorer request failed: UnrecognizedClientException - The security token included in the request is invalid",
            "AWS Cost Explorer request failed: ExpiredTokenException - The security token included in the request is expired",
            "AWS Cost Explorer request failed: SignatureDoesNotMatch - Signature expired",
        ],
    )
    def test_permanent_aws_failures_stop_the_sync_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AWS Cost Explorer request failed: LimitExceededException - Rate exceeded",
            "AWS Cost Explorer request failed: HTTP 503 - ",
        ],
    )
    def test_transient_aws_failures_keep_retrying(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_uses_the_endpoints_primary_key_and_a_stable_partition_key(self, endpoint: str) -> None:
        inputs = make_inputs(endpoint)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == endpoint
        assert response.primary_keys == AWS_COST_EXPLORER_ENDPOINTS[endpoint].primary_key
        assert response.partition_keys == ["period_start"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

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
