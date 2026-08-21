from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.montecarlo import (
    MonteCarloSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source import MonteCarloSource


class TestMonteCarloSource:
    def setup_method(self) -> None:
        self.source = MonteCarloSource()
        self.config = MonteCarloSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    @parameterized.expand([(True, None), (False, "Invalid Monte Carlo API key ID or secret")])
    def test_validate_credentials(self, is_valid: bool, expected_error: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source.validate_monte_carlo_credentials",
            return_value=is_valid,
        ) as mock_validate:
            result, error = self.source.validate_credentials(self.config, team_id=1)

        assert result is is_valid
        assert error == expected_error
        mock_validate.assert_called_once_with("key-id", "key-secret")
