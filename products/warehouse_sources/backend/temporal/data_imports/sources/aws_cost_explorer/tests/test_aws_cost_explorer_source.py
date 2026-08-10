import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer import (
    aws_cost_explorer as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.aws_cost_explorer import (
    AwsCostExplorerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
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
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AWSCOSTEXPLORER

    def test_source_is_released_and_labelled_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.iconPath == "/static/services/aws_cost_explorer.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aws-cost-explorer"

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields

        assert [field.name for field in fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
            "start_date",
        ]

    @pytest.mark.parametrize(
        "field_name,required,secret",
        [
            ("aws_access_key_id", True, False),
            ("aws_secret_access_key", True, True),
            ("aws_session_token", False, True),
            ("start_date", False, False),
        ],
    )
    def test_credential_fields_are_marked_secret_so_they_are_not_echoed_back(
        self, field_name: str, required: bool, secret: bool
    ) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )

        assert field.required is required
        assert field.secret is secret
        assert (field.type == SourceFieldInputConfigType.PASSWORD) is secret

    def test_get_schemas_exposes_every_endpoint_as_incremental_on_the_period_start(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert [field["field"] for field in schema.incremental_fields] == ["period_start"]
            assert schema.description

    def test_get_schemas_honors_the_schema_picker_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["cost_and_usage_monthly"])

        assert [schema.name for schema in schemas] == ["cost_and_usage_monthly"]

    def test_table_catalog_is_listable_without_credentials_for_public_docs(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        assert self.source.get_schemas(AwsCostExplorerSourceConfig(aws_access_key_id="", aws_secret_access_key=""), 1)

    def test_canonical_descriptions_are_keyed_by_the_schema_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

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

    def test_validate_credentials_passes_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "validate_aws_cost_explorer_credentials", return_value=(True, None)) as v:
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

        assert v.call_args[0] == ("AKIAEXAMPLE", "secret", None)

    def test_validate_credentials_surfaces_the_transport_failure_reason(self) -> None:
        with mock.patch.object(source_module, "validate_aws_cost_explorer_credentials", return_value=(False, "denied")):
            assert self.source.validate_credentials(self.config, team_id=1) == (False, "denied")

    def test_resumable_manager_is_bound_to_the_sources_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(make_inputs("cost_and_usage_daily"))

        assert manager._data_class is AwsCostExplorerResumeConfig

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
