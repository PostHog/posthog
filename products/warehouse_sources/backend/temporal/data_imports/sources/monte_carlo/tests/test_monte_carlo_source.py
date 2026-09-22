from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.montecarlo import (
    MonteCarloSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.source import MonteCarloSource


class TestMonteCarloSource:
    def setup_method(self) -> None:
        self.source = MonteCarloSource()
        self.config = MonteCarloSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "monitors"])
        assert {s.name for s in schemas} == {"alerts", "monitors"}

    @parameterized.expand(
        [
            ("alerts", True),
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

    def test_alerts_offers_created_and_updated_time_cursors(self) -> None:
        alerts = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == "alerts")
        assert [f["field"] for f in alerts.incremental_fields] == ["createdTime", "updatedTime"]

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

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
