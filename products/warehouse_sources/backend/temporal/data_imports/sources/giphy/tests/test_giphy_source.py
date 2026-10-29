import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid GIPHY API key"),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message: str | None) -> None:
        status_code = 200 if mock_return else 401
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].param("api_key") == self.config.api_key
