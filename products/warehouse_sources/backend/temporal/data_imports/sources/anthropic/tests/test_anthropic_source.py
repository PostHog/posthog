import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import AnthropicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AnthropicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAnthropicSource:
    def setup_method(self):
        self.source = AnthropicSource()
        self.team_id = 123
        self.config = AnthropicSourceConfig(api_key="sk-ant-admin-test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ANTHROPIC

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Anthropic"
        assert config.label == "Anthropic"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/anthropic.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/anthropic"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.anthropic.com/v1/organizations/users?limit=500",
            "403 Client Error: Forbidden for url: https://api.anthropic.com/v1/organizations/cost_report",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.anthropic.com/v1/organizations/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the report endpoints expose a server-side starting_at filter.
        assert incremental == {"usage_report", "cost_report"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["usage_report"].incremental_fields == INCREMENTAL_FIELDS["usage_report"]
        assert schemas["cost_report"].incremental_fields == INCREMENTAL_FIELDS["cost_report"]
        assert schemas["users"].incremental_fields == []
        assert schemas["users"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["usage_report"])
        assert len(schemas) == 1
        assert schemas[0].name == "usage_report"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Anthropic Admin API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source.validate_anthropic_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AnthropicResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source.anthropic_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_anthropic_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "usage_report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_anthropic_source.assert_called_once()
        kwargs = mock_anthropic_source.call_args.kwargs
        assert kwargs["api_key"] == "sk-ant-admin-test"
        assert kwargs["endpoint"] == "usage_report"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source.anthropic_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_anthropic_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_anthropic_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
