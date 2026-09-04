import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source import AdRollSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adroll import AdRollSourceConfig


class TestAdRollSource:
    def setup_method(self):
        self.source = AdRollSource()
        self.team_id = 123
        self.config = AdRollSourceConfig(client_id="cid", personal_access_token="pat")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://services.adroll.com/api/v1/organization/get_advertisables",
            "403 Client Error: Forbidden for url: https://services.adroll.com/api/v1/campaign/get_all",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://services.adroll.com/api/v1/ad/get_all",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AdRoll credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source.validate_adroll_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("cid", "pat")
