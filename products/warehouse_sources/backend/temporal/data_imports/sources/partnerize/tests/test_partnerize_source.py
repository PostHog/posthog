import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PartnerizeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import (
    PartnerizeResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source import PartnerizeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"conversions", "clicks"}


class TestPartnerizeSource:
    def setup_method(self) -> None:
        self.source = PartnerizeSource()
        self.team_id = 123
        self.config = PartnerizeSourceConfig(
            application_key="app-key", user_api_key="api-key", publisher_id="111111l92"
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PARTNERIZE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Partnerize"
        assert config.label == "Partnerize"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/partnerize"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["application_key", "user_api_key", "publisher_id"]

    def test_user_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "user_api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        for name, schema in by_name.items():
            expected = name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected
            assert bool(schema.incremental_fields) is expected

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["conversions"])
        assert len(schemas) == 1
        assert schemas[0].name == "conversions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)
        by_name = {t["name"]: t for t in tables}
        assert "Incremental" in by_name["conversions"]["sync_methods"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.partnerize.com/reporting/report_publisher/publisher/111111l92/conversion.json?start_date=2010-01-01T00%3A00%3A00Z&offset=0",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.partnerize.com/reference/country",
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
                "500 Server Error: Internal Server Error for url: https://api.partnerize.com/reference/country",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.partnerize.com/reference/currency",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_config_values(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in partnerize.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the delegate's verdict.
        mock_validate.return_value = (False, "Invalid Partnerize API credentials")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("app-key", "api-key", "111111l92")
        assert result == (False, "Invalid Partnerize API credentials")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PartnerizeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"
        inputs.incremental_field = "conversion_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["application_key"] == "app-key"
        assert kwargs["user_api_key"] == "api-key"
        assert kwargs["publisher_id"] == "111111l92"
        assert kwargs["endpoint"] == "conversions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01 12:00:00"
        assert kwargs["incremental_field"] == "conversion_time"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Partnerize schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
