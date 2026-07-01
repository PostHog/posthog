import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OptimizelySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source import OptimizelySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOptimizelySource:
    def setup_method(self):
        self.source = OptimizelySource()
        self.team_id = 123
        self.config = OptimizelySourceConfig(api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OPTIMIZELY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Optimizely"
        assert config.label == "Optimizely"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/optimizely.com.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_non_retryable_errors_match_auth_failures(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        observed = "401 Client Error: Unauthorized for url: https://api.optimizely.com/v2/projects?per_page=100"
        assert any(key in observed for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.optimizely.com/v2/projects",
            # Per-project 403s are skipped in the fan-out, not fatal.
            "403 Client Error: Forbidden for url: https://api.optimizely.com/v2/campaigns",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["experiments"])
        assert len(schemas) == 1
        assert schemas[0].name == "experiments"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Optimizely personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source.validate_optimizely_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source.optimizely_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_optimizely_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "experiments"

        self.source.source_for_pipeline(self.config, inputs)

        mock_optimizely_source.assert_called_once()
        kwargs = mock_optimizely_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "experiments"
