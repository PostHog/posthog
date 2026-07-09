import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import CoinGeckoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source import CoinGeckoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoinGeckoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCoinGeckoSource:
    def setup_method(self) -> None:
        self.source = CoinGeckoSource()
        self.team_id = 123
        self.config = CoinGeckoSourceConfig(api_key="CG-test", plan="demo")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.COINGECKO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "CoinGecko"
        assert config.label == "CoinGecko"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — no unreleasedSource flag.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/coingecko.png"

        assert [f.name for f in config.fields] == ["plan", "api_key"]

    def test_plan_field_is_select_defaulting_to_demo(self) -> None:
        plan_field = next(f for f in self.source.get_source_config.fields if f.name == "plan")
        assert isinstance(plan_field, SourceFieldSelectConfig)
        assert plan_field.defaultValue == "demo"
        assert {option.value for option in plan_field.options} == {"demo", "pro"}

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

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

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["coins_markets"])
        assert len(schemas) == 1
        assert schemas[0].name == "coins_markets"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CoinGeckoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.coingecko_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cg_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "coins_markets"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_cg_source.assert_called_once()
        kwargs = mock_cg_source.call_args.kwargs
        assert kwargs["plan"] == "demo"
        assert kwargs["api_key"] == "CG-test"
        assert kwargs["endpoint"] == "coins_markets"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_key_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert "coins_markets" in descriptions
        assert "current_price" in descriptions["coins_markets"]["columns"]
