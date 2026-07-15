import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TremendousSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.source import TremendousSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous import (
    TremendousResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTremendousSource:
    def setup_method(self) -> None:
        self.source = TremendousSource()
        self.team_id = 123
        self.config = TremendousSourceConfig(api_key="tremendous-key", environment="sandbox")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TREMENDOUS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Tremendous"
        assert config.label == "Tremendous"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tremendous"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "api_key"]

    def test_environment_field_defaults_to_production(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert field.defaultValue == "production"
        assert {o.value for o in field.options} == {"production", "sandbox"}

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_only_orders_is_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        # /orders is the only endpoint with a server-side timestamp filter (created_at[gte]).
        assert by_name["orders"].supports_incremental is True
        assert [f["field"] for f in by_name["orders"].incremental_fields] == ["created_at"]
        for name, schema in by_name.items():
            if name != "orders":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["rewards"])
        assert len(schemas) == 1
        assert schemas[0].name == "rewards"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)
        orders = next(t for t in tables if t["name"] == "orders")
        assert "Incremental" in orders["sync_methods"]
        assert all(t["description"] for t in tables)

    @parameterized.expand(
        [
            (
                "production_unauthorized",
                "401 Client Error: Unauthorized for url: https://www.tremendous.com/api/v2/orders?limit=500&offset=0",
            ),
            (
                "sandbox_unauthorized",
                "401 Client Error: Unauthorized for url: https://testflight.tremendous.com/api/v2/rewards?limit=500&offset=0",
            ),
            (
                "production_forbidden",
                "403 Client Error: Forbidden for url: https://www.tremendous.com/api/v2/members",
            ),
            (
                "sandbox_forbidden",
                "403 Client Error: Forbidden for url: https://testflight.tremendous.com/api/v2/members",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://www.tremendous.com/api/v2/orders",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://testflight.tremendous.com/api/v2/rewards",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.source.validate_tremendous_credentials"
    )
    def test_validate_credentials_delegates_with_key_and_environment(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in tremendous.validate_credentials; here we only assert
        # the source probes with the configured key and environment and returns the verdict unchanged.
        mock_validate.return_value = (False, "Invalid Tremendous API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("tremendous-key", "sandbox")
        assert result == (False, "Invalid Tremendous API key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TremendousResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.source.tremendous_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "tremendous-key"
        assert kwargs["environment"] == "sandbox"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.source.tremendous_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh run and window the sync.
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Tremendous schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
