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

    def test_get_schemas_hides_search_without_query(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        names = {s.name for s in schemas}
        assert names == set(ENDPOINTS) - SEARCH_ENDPOINTS

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config_with_query, self.team_id, names=["gifs_search"])
        assert [s.name for s in schemas] == ["gifs_search"]

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
