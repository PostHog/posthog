import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.giphy import GiphySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.source import GiphySource

# Endpoints that need a user-supplied search query (hidden until one is set).
SEARCH_ENDPOINTS = {"gifs_search", "stickers_search"}


class TestGiphySource:
    def setup_method(self):
        self.source = GiphySource()
        self.team_id = 123
        self.config = GiphySourceConfig(api_key="key", search_query=None)
        self.config_with_query = GiphySourceConfig(api_key="key", search_query="cats")

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
