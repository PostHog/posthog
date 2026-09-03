import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.faire.source import FaireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.faire import FaireSourceConfig

_INCREMENTAL_ENDPOINTS = {"Orders", "Products"}
_FULL_REFRESH_ENDPOINTS = {"Brand"}


class TestFaireSource:
    def setup_method(self):
        self.source = FaireSource()
        self.team_id = 123
        self.config = FaireSourceConfig(api_key="token")

    def test_api_version(self):
        assert self.source.default_version == "v2"
        assert self.source.default_version in self.source.supported_versions
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://www.faire.com/external-api/v2/orders?limit=50",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://www.faire.com/external-api/v2/orders",
            "500 Server Error: Internal Server Error for url: https://www.faire.com/external-api/v2/orders",
            "HTTPSConnectionPool(host='www.faire.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Faire API access token"),
            ((False, 403), False, "Could not connect to Faire with the provided API access token"),
            ((False, None), False, "Could not connect to Faire with the provided API access token"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.faire.source.validate_faire_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token")
