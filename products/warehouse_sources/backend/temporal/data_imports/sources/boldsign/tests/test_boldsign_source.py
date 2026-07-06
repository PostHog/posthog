import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign import BoldSignResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import (
    BOLDSIGN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source import BoldSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BoldSignSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBoldSignSource:
    def setup_method(self):
        self.source = BoldSignSource()
        self.team_id = 123
        self.config = BoldSignSourceConfig(api_key="key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BOLDSIGN

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "BoldSign"
        assert config.label == "BoldSign"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/boldsign"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "region"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_region_field_is_a_select_with_us_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog (no I/O) so the public docs can render Supported tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.boldsign.com/v1/document/list?Page=1",
            "401 Client Error: Unauthorized for url: https://api-eu.boldsign.com/v1/template/list?Page=1",
            "403 Client Error: Forbidden for url: https://api.boldsign.com/v1/users/list",
            "403 Client Error: Forbidden for url: https://api-eu.boldsign.com/v1/teams/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.boldsign.com/v1/document/list",
            "500 Server Error: Internal Server Error for url: https://api.boldsign.com/v1/document/list",
            "HTTPSConnectionPool(host='api.boldsign.com', port=443): Read timed out.",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # BoldSign has no reliable updated-since cursor, so nothing supports incremental/append.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_expose_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["documents"].detected_primary_keys == ["documentId"]
        assert schemas["teams"].detected_primary_keys == ["teamId"]
        assert schemas["contacts"].detected_primary_keys == ["id"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["documents"])
        assert len(schemas) == 1
        assert schemas[0].name == "documents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self):
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        documents = next(t for t in tables if t["name"] == "documents")
        assert documents["sync_methods"] == ["Full refresh"]
        assert documents["primary_keys"] == ["documentId"]
        assert documents["description"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid BoldSign API key"), False, "Invalid BoldSign API key"),
            ((False, "Could not reach BoldSign: timed out"), False, "Could not reach BoldSign: timed out"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source.validate_boldsign_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us", "key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BoldSignResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source.boldsign_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bs_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "documents"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bs_source.assert_called_once()
        kwargs = mock_bs_source.call_args.kwargs
        assert kwargs["region"] == "us"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "documents"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(BOLDSIGN_ENDPOINTS.keys())
