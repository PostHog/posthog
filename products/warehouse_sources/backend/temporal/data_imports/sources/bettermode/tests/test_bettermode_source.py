import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source import BettermodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bettermode import (
    BettermodeSourceConfig,
)


class TestBettermodeSource:
    def setup_method(self):
        self.source = BettermodeSource()
        self.team_id = 123
        self.config = BettermodeSourceConfig(region="us", client_id="client", client_secret="secret", network_id="net")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only `posts` has a server-side timestamp filter; everything else is full refresh.
        assert incremental == {"posts"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Bettermode API error (status 404): App not found"),
                False,
                "Bettermode API error (status 404): App not found",
            ),
            ((False, None), False, "Invalid Bettermode credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source.validate_bettermode_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us", "client", "secret", "net")
