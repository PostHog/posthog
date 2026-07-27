import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source import EppoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eppo import EppoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Only "Experiments" documents a server-side timestamp filter (created_since/updated_since).
_INCREMENTAL_ENDPOINTS = {"Experiments"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestEppoSource:
    def setup_method(self):
        self.source = EppoSource()
        self.team_id = 123
        self.config = EppoSourceConfig(api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.EPPO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Eppo"
        assert config.label == "Eppo (Datadog)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/eppo.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/eppo"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_api_docs_url_is_set(self):
        assert self.source.api_docs_url == "https://eppo.cloud/api/docs"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://eppo.cloud/api/v1/experiments?limit=100",
            "403 Client Error: Forbidden for url: https://eppo.cloud/api/v1/experiments?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://eppo.cloud/api/v1/experiments",
            "500 Server Error: Internal Server Error for url: https://eppo.cloud/api/v1/experiments",
            "HTTPSConnectionPool(host='eppo.cloud', port=443): Read timed out.",
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
            assert [f["field"] for f in schemas[name].incremental_fields] == ["created_date"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Metrics"])
        assert len(schemas) == 1
        assert schemas[0].name == "Metrics"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_message",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid Eppo API key"),
            # A valid key that lacks scope for one resource must not block source-create.
            ((False, 403), None, True, None),
            # ...but a per-table scope check on a specific schema should still surface it.
            ((False, 403), "Experiments", False, "Invalid Eppo API key"),
            ((False, None), None, False, "Invalid Eppo API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source.validate_eppo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, schema_name, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source.eppo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_eppo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Experiments"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.incremental_field = "created_date"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_eppo_source.assert_called_once_with(
            api_key="key",
            endpoint="Experiments",
            team_id=self.team_id,
            job_id="job-1",
            incremental_field="created_date",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
