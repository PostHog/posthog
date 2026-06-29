from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.financial_modelling import (
    FinancialModellingResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source import (
    FinancialModellingSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestFinancialModellingSourceConfig:
    def test_source_type(self) -> None:
        assert FinancialModellingSource().source_type == ExternalDataSourceType.FINANCIALMODELLING

    def test_source_config_basics(self) -> None:
        config = FinancialModellingSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/financial-modelling"

    def test_fields(self) -> None:
        fields = {f.name: f for f in FinancialModellingSource().get_source_config.fields}
        assert set(fields) == {"api_key", "symbols"}
        api_key, symbols = fields["api_key"], fields["symbols"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(symbols, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert symbols.required is True
        assert symbols.secret is False


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


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://financialmodelingprep.com/stable/profile?symbol=AAPL",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://financialmodelingprep.com/stable/income-statement?symbol=AAPL",
            ),
            (
                "error_body",
                "Financial Modeling Prep API returned an error response: Exclusive Endpoint: This endpoint is only for premium subscribers.",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FinancialModellingSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://financialmodelingprep.com/stable/profile",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://financialmodelingprep.com/stable/profile",
            ),
            ("timeout", "Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FinancialModellingSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableSourceManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = FinancialModellingSource().get_resumable_source_manager(_inputs("historical_prices"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FinancialModellingResumeConfig


class TestSourceForPipeline:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source.financial_modelling_source"
    )
    def test_parses_symbols_and_plumbs_arguments(self, mock_source: MagicMock) -> None:
        config = FinancialModellingSource().parse_config({"api_key": "k", "symbols": "aapl, msft"})
        FinancialModellingSource().source_for_pipeline(config, MagicMock(), _inputs("company_profiles"))
        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "k"
        assert kwargs["symbols"] == ["AAPL", "MSFT"]
        assert kwargs["endpoint"] == "company_profiles"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.source.financial_modelling_source"
    )
    def test_last_value_passed_only_when_incremental(self, mock_source: MagicMock) -> None:
        config = FinancialModellingSource().parse_config({"api_key": "k", "symbols": "AAPL"})

        FinancialModellingSource().source_for_pipeline(
            config,
            MagicMock(),
            _inputs(
                "historical_prices", should_use_incremental_field=True, db_incremental_field_last_value="2024-01-01"
            ),
        )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == "2024-01-01"

        FinancialModellingSource().source_for_pipeline(
            config,
            MagicMock(),
            _inputs(
                "historical_prices", should_use_incremental_field=False, db_incremental_field_last_value="2024-01-01"
            ),
        )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestPublicDocs:
    def test_lists_tables_without_credentials(self) -> None:
        assert FinancialModellingSource().lists_tables_without_credentials is True

    def test_documented_tables_cover_every_endpoint(self) -> None:
        tables = {t["name"] for t in FinancialModellingSource().get_documented_tables()}
        assert tables == set(ENDPOINTS)

    def test_canonical_descriptions_keys_are_valid_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
