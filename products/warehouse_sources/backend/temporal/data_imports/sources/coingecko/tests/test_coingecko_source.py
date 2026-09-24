import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
    ENDPOINTS,
    MAX_COINS,
    MERGE_ONLY_ENDPOINTS,
    PER_COIN_ENDPOINTS,
    PRO_ONLY_ENDPOINTS,
)
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

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the timeseries endpoints take a server-side date filter, and they re-read the window
        # holding the last synced day, so append would duplicate every day in that overlap.
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == set(MERGE_ONLY_ENDPOINTS)
        assert all(not schema.supports_append for schema in schemas.values())
        # On a Demo key the per-coin endpoints can't sync until coin IDs are configured and the
        # Pro-only ones can't sync at all, so one-shot setup must not enable either.
        assert {name for name, schema in schemas.items() if not schema.should_sync_default} == set(
            PER_COIN_ENDPOINTS
        ) | set(PRO_ONLY_ENDPOINTS)

    def test_pro_plan_enables_the_pro_only_endpoints(self) -> None:
        config = CoinGeckoSourceConfig(api_key="CG-test", plan="pro")

        schemas = {schema.name: schema for schema in self.source.get_schemas(config, self.team_id)}

        assert all(schemas[name].should_sync_default for name in PRO_ONLY_ENDPOINTS)

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

    @pytest.mark.parametrize("schema_name", PER_COIN_ENDPOINTS)
    def test_per_coin_schema_needs_coin_ids(self, schema_name: str) -> None:
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is False
        assert error_message == "Add at least one coin ID to sync this table."

    @pytest.mark.parametrize("schema_name", PRO_ONLY_ENDPOINTS)
    def test_pro_only_schema_is_refused_on_a_demo_key(self, schema_name: str) -> None:
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is False
        assert error_message == "This table needs a CoinGecko Pro key on the Analyst plan or above."

    @pytest.mark.parametrize("schema_name", PRO_ONLY_ENDPOINTS)
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.validate_coingecko_credentials"
    )
    def test_pro_only_schema_connects_on_a_pro_key(self, mock_validate: mock.MagicMock, schema_name: str) -> None:
        mock_validate.return_value = True
        config = CoinGeckoSourceConfig(api_key="CG-test", plan="pro")

        assert self.source.validate_credentials(config, self.team_id, schema_name) == (True, None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.validate_coingecko_credentials"
    )
    def test_market_wide_schema_connects_without_coin_ids(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id, "coins_list") == (True, None)

    @pytest.mark.parametrize("start_date", ["", "   ", None])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.validate_coingecko_credentials"
    )
    def test_blank_start_date_falls_back_to_the_default_window(
        self, mock_validate: mock.MagicMock, start_date: str | None
    ) -> None:
        mock_validate.return_value = True
        config = CoinGeckoSourceConfig(api_key="CG-test", plan="demo", start_date=start_date)

        assert self.source.validate_credentials(config, self.team_id) == (True, None)

    @pytest.mark.parametrize(
        "config_kwargs, expected_message",
        [
            (
                {"coin_ids": ",".join(f"coin-{i}" for i in range(MAX_COINS + 1))},
                f"Too many coin IDs. List at most {MAX_COINS}.",
            ),
            ({"start_date": "1970-01-01"}, "CoinGecko has no data before 2018-01-01. Enter that date or a later one."),
            (
                # An unreadable date silently fell back to the default window, so the source synced
                # a different range than the one that was configured.
                {"start_date": "01/15/2025"},
                "Couldn't read '01/15/2025' as a date. Use the format YYYY-MM-DD, for example 2025-01-01.",
            ),
        ],
    )
    def test_rejects_a_configuration_that_would_run_away(
        self, config_kwargs: dict[str, str], expected_message: str
    ) -> None:
        config = CoinGeckoSourceConfig(api_key="CG-test", plan="demo", **config_kwargs)

        assert self.source.validate_credentials(config, self.team_id) == (False, expected_message)
