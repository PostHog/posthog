import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyros import HyrosSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.hyros import HyrosResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.settings import ENDPOINTS, HYROS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source import HyrosSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"Leads", "Sales", "Calls", "Subscriptions"}
_FULL_REFRESH_ENDPOINTS = {"Sources", "Tags", "Keywords", "Stages"}


class TestHyrosSource:
    def setup_method(self):
        self.source = HyrosSource()
        self.team_id = 123
        self.config = HyrosSourceConfig(api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HYROS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Hyros"
        assert config.label == "Hyros"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/hyros.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hyros"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_api_version_metadata(self):
        assert self.source.supported_versions == ("v1.0",)
        assert self.source.default_version == "v1.0"
        assert self.source.api_docs_url == "https://api-docs.hyros.com"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.hyros.com/v1/api/v1.0/leads",
            "403 Client Error: Forbidden for url: https://api.hyros.com/v1/api/v1.0/calls",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.hyros.com/v1/api/v1.0/leads",
            "500 Server Error: Internal Server Error for url: https://api.hyros.com/v1/api/v1.0/leads",
            "HTTPSConnectionPool(host='api.hyros.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            expected_field = HYROS_ENDPOINTS[name].incremental_field_name
            assert [f["field"] for f in schemas[name].incremental_fields] == [expected_field]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Leads"])
        assert len(schemas) == 1
        assert schemas[0].name == "Leads"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(HYROS_ENDPOINTS)

    @parameterized.expand(
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Hyros API key"),
            ((False, 403), False, "Invalid Hyros API key"),
            ((False, None), False, "Invalid Hyros API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source.validate_hyros_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message_prefix, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_prefix is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert error_message.startswith(expected_message_prefix)
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is HyrosResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source.hyros_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hyros_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_hyros_source.assert_called_once()
        kwargs = mock_hyros_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "Leads"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source.hyros_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_hyros_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Stages"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_hyros_source.call_args.kwargs["db_incremental_field_last_value"] is None
