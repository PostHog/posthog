import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShopWiredSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.shopwired import ShopWiredResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source import ShopWiredSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestShopWiredSource:
    def setup_method(self) -> None:
        self.source = ShopWiredSource()
        self.team_id = 123
        self.config = ShopWiredSourceConfig(api_key="sw-key", api_secret="sw-secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SHOPWIRED

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "ShopWired"
        assert config.label == "ShopWired"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/shopwired"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret"]

    @parameterized.expand([("api_key",), ("api_secret",)])
    def test_credential_fields_are_secret_passwords(self, field_name: str) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secrets and the base URL is hardcoded, so there is no non-secret field an
        # editor could retarget to reuse preserved credentials against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_only_orders_supports_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        assert by_name["orders"].supports_incremental is True
        assert [f["field"] for f in by_name["orders"].incremental_fields] == ["created"]
        for name, schema in by_name.items():
            if name == "orders":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)
        orders = next(t for t in tables if t["name"] == "orders")
        assert "Incremental" in orders["sync_methods"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.ecommerceapi.uk/v1/orders?count=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.ecommerceapi.uk/v1/products?count=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.ecommerceapi.uk/v1/orders"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.ecommerceapi.uk/v1/products"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_credentials(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in shopwired.validate_credentials; here we only assert the
        # source probes with the configured credentials and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid ShopWired API key or secret")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("sw-key", "sw-secret")
        assert result == (False, "Invalid ShopWired API key or secret")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ShopWiredResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source.shopwired_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sw-key"
        assert kwargs["api_secret"] == "sw-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown ShopWired schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
