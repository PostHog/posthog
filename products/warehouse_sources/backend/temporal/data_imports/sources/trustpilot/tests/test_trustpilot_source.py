from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    ENDPOINTS,
    TRUSTPILOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source import TrustPilotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    TrustpilotResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTrustPilotSource:
    def setup_method(self):
        self.source = TrustPilotSource()
        self.team_id = 123
        self.config = TrustPilotSourceConfig(api_key="key", api_secret="secret", business_unit="example.com")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TRUSTPILOT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "TrustPilot"
        assert config.label == "Trustpilot"
        # A finished source ships visible with a soft ALPHA label, never hidden.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/trustpilot"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret", "business_unit"]

    @parameterized.expand(["api_key", "api_secret"])
    def test_credential_fields_are_secret_passwords(self, field_name):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.trustpilot.com/v1/private/business-units/x/reviews",
            "403 Client Error: Forbidden for url: https://api.trustpilot.com/v1/private/product-reviews/business-units/x/reviews",
            "404 Client Error: Not Found for url: https://api.trustpilot.com/v1/business-units/x",
            "No Trustpilot business unit found for 'example.com'. Enter your domain exactly as it appears.",
            "Trustpilot rejected the API key (HTTP 401). Check the API key in your Trustpilot Business account.",
            "invalid_client from the OAuth2 token endpoint [oauth2_token_config_error]",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            "429 Client Error: Too Many Requests for url: https://api.trustpilot.com/v1/business-units/x/reviews",
            "500 Server Error: Internal Server Error for url: https://api.trustpilot.com/v1/business-units/x",
            "HTTP 503 from the OAuth2 token endpoint",
            "HTTPSConnectionPool(host='api.trustpilot.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert schemas["service_reviews"].supports_incremental is True
        assert schemas["service_reviews"].supports_append is True
        assert [f["field"] for f in schemas["service_reviews"].incremental_fields] == ["createdAt"]
        for name in ("business_unit", "product_reviews"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["service_reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "service_reviews"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(TRUSTPILOT_ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source.validate_trustpilot_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate):
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("key", "secret", "example.com")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is TrustpilotResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source.trustpilot_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_trustpilot_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "service_reviews"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_trustpilot_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["api_secret"] == "secret"
        assert kwargs["business_unit"] == "example.com"
        assert kwargs["endpoint"] == "service_reviews"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source.trustpilot_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_trustpilot_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "product_reviews"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_trustpilot_source.call_args.kwargs["db_incremental_field_last_value"] is None
