import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source import CoinGeckoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coingecko import (
    CoinGeckoSourceConfig,
)


class TestCoinGeckoSource:
    def setup_method(self) -> None:
        self.source = CoinGeckoSource()
        self.team_id = 123
        self.config = CoinGeckoSourceConfig(api_key="CG-test", plan="demo")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.coingecko.com/api/v3/coins/markets",
            "401 Client Error: Unauthorized for url: https://pro-api.coingecko.com/api/v3/exchanges",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.coingecko.com/api/v3/coins/list",
            "500 Server Error for url: https://api.coingecko.com/api/v3/exchanges",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # CoinGecko's catalog/snapshot endpoints have no server-side timestamp filter.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your CoinGecko API key. Check that the key is correct and that CoinGecko is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.validate_coingecko_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("demo", "CG-test")
