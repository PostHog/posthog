import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.source import FastlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FastlySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFastlySource:
    def setup_method(self):
        self.source = FastlySource()
        self.team_id = 123
        self.config = FastlySourceConfig(api_key="token123")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FASTLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Fastly"
        assert config.label == "Fastly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/fastly.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/fastly"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs render tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.fastly.com/current_user",
            "403 Client Error: Forbidden for url: https://api.fastly.com/service/abc/version/1/backend",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.fastly.com/service",
            "429 Client Error: Too Many Requests for url: https://api.fastly.com/service",
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

    def test_get_schemas_have_descriptions(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(schema.description for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["services"])
        assert len(schemas) == 1
        assert schemas[0].name == "services"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Fastly API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fastly.source.validate_fastly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token123")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.fastly import FastlyResumeConfig

        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is FastlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fastly.source.fastly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_fastly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "services"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_fastly_source.assert_called_once()
        kwargs = mock_fastly_source.call_args.kwargs
        assert kwargs["api_key"] == "token123"
        assert kwargs["endpoint"] == "services"
        assert kwargs["resumable_source_manager"] is manager
