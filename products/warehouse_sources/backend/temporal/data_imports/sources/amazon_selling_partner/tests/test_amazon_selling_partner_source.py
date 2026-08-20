from typing import Optional

import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    AmazonSellingPartnerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.source import (
    AmazonSellingPartnerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonsellingpartner import (
    AmazonSellingPartnerRegionConfig,
    AmazonSellingPartnerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.source"


class TestAmazonSellingPartnerSource:
    def setup_method(self) -> None:
        self.source = AmazonSellingPartnerSource()
        self.team_id = 123
        self.config = AmazonSellingPartnerSourceConfig(
            region=AmazonSellingPartnerRegionConfig(selection="na", amazon_selling_partner_integration_id=7),
            marketplace_ids="ATVPDKIKX0DER",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AMAZONSELLINGPARTNER

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "AmazonSellingPartner"
        assert config.label == "Amazon Selling Partner"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/amazon_selling_partner.png"

        assert [f.name for f in config.fields] == ["region", "marketplace_ids"]

    def test_region_field_is_a_select_over_the_supported_hosts(self) -> None:
        region_field = next(f for f in self.source.get_source_config.fields if f.name == "region")

        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "na"
        assert {option.value for option in region_field.options} == {"na", "eu", "fe"}

    @pytest.mark.parametrize(
        "region, expected_kind",
        [
            ("na", "amazon-selling-partner-na"),
            ("eu", "amazon-selling-partner-eu"),
            ("fe", "amazon-selling-partner-fe"),
        ],
    )
    def test_each_region_connects_through_its_own_integration_kind(self, region: str, expected_kind: str) -> None:
        # A seller can only consent on the Seller Central for their own region, so the Connect
        # button under each region has to point at that region's integration kind.
        region_field = next(f for f in self.source.get_source_config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        option = next(o for o in region_field.options if o.value == region)

        assert option.fields is not None
        oauth_field = option.fields[0]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "amazon_selling_partner_integration_id"
        assert oauth_field.kind == expected_kind

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Missing integration ID",
            "Integration not found: 7",
            "401 Client Error: Unauthorized for url: https://sellingpartnerapi-na.amazon.com/orders/v0/orders",
            "403 Client Error: Forbidden for url: https://sellingpartnerapi-eu.amazon.com/fba/inventory/v1/summaries",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://sellingpartnerapi-na.amazon.com/orders/v0/orders",
            "401 Client Error: Unauthorized for url: https://advertising-api.amazon.com/v2/profiles",
        ],
    )
    def test_non_retryable_errors_do_not_match_throttles_or_other_vendors(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_internal_throttle_errors_are_reported_as_retryable(self) -> None:
        error = "Amazon Selling Partner API error (retryable): status=429, url=https://sellingpartnerapi-na.amazon.com"

        assert any(key in error for key in self.source.get_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_advertises_its_incremental_field(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])

        assert [schema.name for schema in schemas] == ["orders"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "helper_result, expected",
        [
            ((True, None), (True, None)),
            (
                (False, "Could not reach the Amazon Selling Partner API."),
                (False, "Could not reach the Amazon Selling Partner API."),
            ),
        ],
    )
    @mock.patch(f"{_MODULE}.amazon_selling_partner_token_provider")
    @mock.patch.object(AmazonSellingPartnerSource, "get_oauth_integration")
    @mock.patch(f"{_MODULE}.validate_amazon_selling_partner_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_get_integration: mock.MagicMock,
        mock_provider: mock.MagicMock,
        helper_result: tuple[bool, Optional[str]],
        expected: tuple[bool, Optional[str]],
    ) -> None:
        mock_validate.return_value = helper_result

        assert self.source.validate_credentials(self.config, self.team_id) == expected
        mock_get_integration.assert_called_once_with(7, self.team_id)
        mock_validate.assert_called_once_with("na", mock_provider.return_value)

    @pytest.mark.parametrize(
        "raised, expected_error",
        [
            (ValueError("Missing integration ID"), "no Amazon seller account connected"),
            (ValueError("Integration not found: 7"), "was removed"),
        ],
    )
    @mock.patch.object(AmazonSellingPartnerSource, "get_oauth_integration")
    def test_validate_credentials_without_a_usable_integration(
        self, mock_get_integration: mock.MagicMock, raised: ValueError, expected_error: str
    ) -> None:
        mock_get_integration.side_effect = raised

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert expected_error in error

    def test_get_resumable_source_manager_isolates_state_per_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = 1
        inputs.job_id = "job"

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AmazonSellingPartnerResumeConfig
        assert manager._key.endswith(":orders")

    @mock.patch(f"{_MODULE}.amazon_selling_partner_token_provider")
    @mock.patch.object(AmazonSellingPartnerSource, "get_oauth_integration")
    @mock.patch(f"{_MODULE}.amazon_selling_partner_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_source: mock.MagicMock, mock_get_integration: mock.MagicMock, mock_provider: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_provider.assert_called_once_with(7, self.team_id)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "na"
        assert kwargs["marketplace_ids"] == "ATVPDKIKX0DER"
        assert kwargs["access_token_provider"] is mock_provider.return_value
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"

    @mock.patch(f"{_MODULE}.amazon_selling_partner_token_provider")
    @mock.patch.object(AmazonSellingPartnerSource, "get_oauth_integration")
    @mock.patch(f"{_MODULE}.amazon_selling_partner_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(
        self, mock_source: mock.MagicMock, mock_get_integration: mock.MagicMock, mock_provider: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
