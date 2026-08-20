from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opencorporates import (
    OpencorporatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
    OpencorporatesResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.settings import (
    ENDPOINTS,
    OPENCORPORATES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source import OpencorporatesSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOpencorporatesSource:
    def setup_method(self):
        self.source = OpencorporatesSource()
        self.team_id = 123
        self.config = OpencorporatesSourceConfig(api_token="token", query="acme", jurisdiction_code=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OPENCORPORATES

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Opencorporates"
        assert config.label == "OpenCorporates"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/opencorporates.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/opencorporates"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token", "query", "jurisdiction_code"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_query_field_is_required(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "query")
        assert field.required is True
        assert field.secret is False

    def test_jurisdiction_code_field_is_optional(self):
        config = self.source.get_source_config
        field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "jurisdiction_code"
        )
        assert field.required is False

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("403 Client Error: Forbidden for url: https://api.opencorporates.com/v0.4/companies/search",),
        ]
    )
    def test_non_retryable_errors_match_auth_and_quota_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("500 Server Error: Internal Server Error for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("HTTPSConnectionPool(host='api.opencorporates.com', port=443): Read timed out.",),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert schemas["Companies"].supports_incremental is True
        assert schemas["Companies"].supports_append is True
        assert [f["field"] for f in schemas["Companies"].incremental_fields] == ["updated_at"]
        assert schemas["Officers"].supports_incremental is False
        assert schemas["Officers"].supports_append is False
        assert schemas["Officers"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Companies"])
        assert len(schemas) == 1
        assert schemas[0].name == "Companies"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(OPENCORPORATES_ENDPOINTS)

    @parameterized.expand(
        [
            ((True, None), True, None),
            ((False, "Invalid OpenCorporates API token"), False, "Invalid OpenCorporates API token"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source.validate_opencorporates_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is OpencorporatesResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source.opencorporates_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_opencorporates_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Companies"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()
        config = OpencorporatesSourceConfig(api_token="token", query="acme", jurisdiction_code="gb")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_opencorporates_source.assert_called_once()
        kwargs = mock_opencorporates_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["query"] == "acme"
        assert kwargs["jurisdiction_code"] == "gb"
        assert kwargs["endpoint"] == "Companies"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source.opencorporates_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_opencorporates_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Officers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_opencorporates_source.call_args.kwargs["db_incremental_field_last_value"] is None
