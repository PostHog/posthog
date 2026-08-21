from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source import (
    FinancialModellingSource,
)


class TestGetSchemas:
    def test_all_endpoints_present(self) -> None:
        schemas = FinancialModellingSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("stock_list", False),
            ("company_profiles", False),
            ("income_statements", False),
            ("historical_prices", True),
            ("earnings_calendar", True),
            ("dividends_calendar", True),
        ]
    )
    def test_incremental_support_matches_date_window(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in FinancialModellingSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is expected_incremental
        # supports_append tracks incremental here (date-windowed endpoints can append).
        assert schemas[endpoint].supports_append is expected_incremental

    def test_names_filter(self) -> None:
        schemas = FinancialModellingSource().get_schemas(MagicMock(), team_id=1, names=["historical_prices"])
        assert [s.name for s in schemas] == ["historical_prices"]


class TestValidateCredentials:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source.validate_financial_modelling_credentials"
    )
    def test_valid(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = True
        config = FinancialModellingSource().parse_config({"api_key": "k", "symbols": "AAPL"})
        ok, error = FinancialModellingSource().validate_credentials(config, team_id=1)
        assert ok is True
        assert error is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source.validate_financial_modelling_credentials"
    )
    def test_invalid(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = False
        config = FinancialModellingSource().parse_config({"api_key": "bad", "symbols": "AAPL"})
        ok, error = FinancialModellingSource().validate_credentials(config, team_id=1)
        assert ok is False
        assert error is not None
