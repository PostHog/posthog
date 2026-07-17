import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.source import CodaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCodaSource:
    def setup_method(self):
        self.source = CodaSource()
        self.team_id = 123
        self.config = CodaSourceConfig(api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CODA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Coda"
        assert config.label == "Coda"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/coda.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://coda.io/apis/v1/docs",
            "403 Client Error: Forbidden for url: https://coda.io/apis/v1/docs/doc1/tables",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://coda.io/apis/v1/docs",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["rows"])
        assert len(schemas) == 1
        assert schemas[0].name == "rows"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Coda API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coda.source.validate_coda_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coda.source.coda_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_coda_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "rows"

        self.source.source_for_pipeline(self.config, inputs)

        mock_coda_source.assert_called_once()
        kwargs = mock_coda_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "rows"
