from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.montecarlo import (
    MonteCarloSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source import MonteCarloSource


class TestMonteCarloSource:
    def setup_method(self) -> None:
        self.source = MonteCarloSource()
        self.config = MonteCarloSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    @parameterized.expand(
        [
            ("alerts", True),
            ("dbt_runs", False),
            ("dbt_test_results", True),
            ("domains", False),
            ("events", True),
            ("fh_events", True),
            ("job_executions", True),
            ("job_schedules", False),
            ("monitors", False),
            ("tables", False),
            ("users", False),
            ("warehouses", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, supports_incremental: bool) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Alerts mutate in place (status/severity), so no endpoint offers append mode.
        assert schema.supports_append is False

    @parameterized.expand([(True, None), (False, "Invalid Monte Carlo API key ID or secret")])
    def test_validate_credentials(self, is_valid: bool, expected_error: str | None) -> None:
        response = (
            ScriptedResponse(json={"data": {"getUser": {"email": "a@example.com"}}})
            if is_valid
            else ScriptedResponse(status=401)
        )
        with scripted_network([response]) as network:
            result, error = self.source.validate_credentials(self.config, team_id=1)

        assert result is is_valid
        assert error == expected_error
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["x-mcd-id"] == "key-id"
        assert network.requests_log[0].headers["x-mcd-token"] == "key-secret"
