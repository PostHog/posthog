import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GiphySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy import GiphyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.source import GiphySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints that need a user-supplied search query (hidden until one is set).
SEARCH_ENDPOINTS = {"gifs_search", "stickers_search"}


class TestGiphySource:
    def setup_method(self):
        self.source = GiphySource()
        self.team_id = 123
        self.config = GiphySourceConfig(api_key="key", search_query=None)
        self.config_with_query = GiphySourceConfig(api_key="key", search_query="cats")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GIPHY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Giphy"
        assert config.label == "Giphy"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/giphy.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "search_query"]

    def test_api_key_field_is_secret_password_required(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_search_query_field_is_optional_text(self):
        config = self.source.get_source_config
        query_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "search_query"
        )
        assert query_field.type == SourceFieldInputConfigType.TEXT
        assert query_field.required is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.giphy.com/v1/gifs/trending?api_key=x&limit=50&offset=0",
            "403 Client Error: Forbidden for url: https://api.giphy.com/v1/gifs/search?api_key=x&q=cats",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.giphy.com/v1/gifs/trending",
            "HTTPSConnectionPool(host='api.giphy.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_missing_search_query_error_is_non_retryable(self):
        # The ValueError raised when a search table syncs without a query must fail fast, not retry.
        observed_error = (
            "GIPHY endpoint 'gifs_search' requires a search query. Set the search query on the source and reconnect."
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_get_schemas_hides_search_without_query(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        names = {s.name for s in schemas}
        assert names == set(ENDPOINTS) - SEARCH_ENDPOINTS

    def test_get_schemas_shows_search_with_query(self):
        schemas = self.source.get_schemas(self.config_with_query, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config_with_query, self.team_id)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_trending_search_terms_off_by_default(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config_with_query, self.team_id)}
        assert schemas["trending_search_terms"].should_sync_default is False
        assert schemas["gifs_trending"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config_with_query, self.team_id, names=["gifs_search"])
        assert [s.name for s in schemas] == ["gifs_search"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config_with_query, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid GIPHY API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.giphy.source.validate_giphy_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GiphyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.giphy.source.giphy_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_giphy_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "gifs_search"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config_with_query, manager, inputs)

        mock_giphy_source.assert_called_once()
        kwargs = mock_giphy_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "gifs_search"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["search_query"] == "cats"

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
        for endpoint in ENDPOINTS:
            assert descriptions[endpoint]["description"]
