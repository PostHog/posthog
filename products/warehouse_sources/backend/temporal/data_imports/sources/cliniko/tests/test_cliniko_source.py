import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source import ClinikoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cliniko import (
    ClinikoSourceConfig,
)


class TestClinikoSource:
    def setup_method(self) -> None:
        self.source = ClinikoSource()
        self.team_id = 123
        self.config = ClinikoSourceConfig(api_key="test-key-au1")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Cliniko"
        assert config.label == "Cliniko"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — no unreleasedSource flag hiding it.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/cliniko.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cliniko"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.au1.cliniko.com/v1/patients?per_page=1",
            "403 Client Error: Forbidden for url: https://api.au1.cliniko.com/v1/patients?per_page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.au1.cliniko.com/v1/patients",
            "500 Server Error: Internal Server Error for url: https://api.au1.cliniko.com/v1/patients",
            "HTTPSConnectionPool(host='api.au1.cliniko.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self) -> None:
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source.validate_cliniko_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key-au1")
