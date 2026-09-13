import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.housecallpro import (
    HousecallProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source import HousecallProSource


class TestHousecallProSource:
    def setup_method(self) -> None:
        self.source = HousecallProSource()
        self.team_id = 123
        self.config = HousecallProSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.housecallpro.com/customers?page=1",
            "403 Client Error: Forbidden for url: https://api.housecallpro.com/jobs",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.housecallpro.com/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_only_invoices_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only Invoices documents a genuine server-side timestamp filter (created_at_min).
        assert incremental == {"invoices"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Housecall Pro API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source.validate_housecall_pro_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
