import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.aha_ideas import AhaIdeasResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.settings import (
    AHA_IDEAS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source import AhaIdeasSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahaideas import (
    AhaIdeasSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints whose Aha! Ideas list action exposes the server-side `updated_since` filter.
_INCREMENTAL_ENDPOINTS = {"ideas", "idea_organizations", "idea_users", "idea_endorsements"}
_FULL_REFRESH_ENDPOINTS = {"idea_portals", "idea_themes", "idea_comments"}


class TestAhaIdeasSource:
    def setup_method(self):
        self.source = AhaIdeasSource()
        self.team_id = 123
        self.config = AhaIdeasSourceConfig(subdomain="acme", api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.AHAIDEAS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "AhaIdeas"
        assert config.label == "Aha! Ideas"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/aha_ideas.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aha-ideas"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_subdomain_listed_as_connection_host_field(self):
        # The API key is sent to <subdomain>.aha.io, so retargeting the subdomain must re-require it.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.aha.io/api/v1/ideas?page=1&per_page=200",
            "403 Client Error: Forbidden for url: https://acme.aha.io/api/v1/idea_portals?page=1&per_page=200",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.aha.io/api/v1/ideas",
            "500 Server Error: Internal Server Error for url: https://acme.aha.io/api/v1/ideas",
            "HTTPSConnectionPool(host='acme.aha.io', port=443): Read timed out.",
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
            assert [f["field"] for f in schemas[name].incremental_fields] == ["updated_at"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["ideas"])
        assert len(schemas) == 1
        assert schemas[0].name == "ideas"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(AHA_IDEAS_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Aha! API key"),
            ((False, 403), False, "Could not connect to Aha! with the provided account domain and API key"),
            ((False, None), False, "Could not connect to Aha! with the provided account domain and API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source.validate_aha_ideas_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source.validate_aha_ideas_credentials"
    )
    def test_validate_credentials_surfaces_bad_subdomain(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Aha! account domain: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Aha! account domain" in (error_message or "")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is AhaIdeasResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source.aha_ideas_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_aha_ideas_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "ideas"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updated_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_aha_ideas_source.assert_called_once()
        kwargs = mock_aha_ideas_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "ideas"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source.aha_ideas_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_aha_ideas_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "idea_portals"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_aha_ideas_source.call_args.kwargs["db_incremental_field_last_value"] is None
