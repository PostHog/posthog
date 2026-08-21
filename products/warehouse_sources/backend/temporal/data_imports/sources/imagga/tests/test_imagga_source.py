import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imagga import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source import ImaggaSource


class TestImaggaSource:
    def setup_method(self) -> None:
        self.source = ImaggaSource()
        self.team_id = 123
        self.config = ImaggaSourceConfig(api_key="acc_test", api_secret="secret_test")

    @pytest.mark.parametrize(
        "observed_error,should_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.imagga.com/v2/usage?concurrency=1", True),
            ("403 Client Error: Forbidden for url: https://api.imagga.com/v2/usage", True),
            ("429 Client Error: Too Many Requests for url: https://api.imagga.com/v2/usage", False),
            ("500 Server Error for url: https://api.imagga.com/v2/usage", False),
        ],
    )
    def test_non_retryable_errors_match_only_auth_failures(self, observed_error: str, should_match: bool) -> None:
        matched = any(key in observed_error for key in self.source.get_non_retryable_errors())
        assert matched is should_match

    @pytest.mark.parametrize(
        "probe_result,expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source.validate_imagga_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, probe_result: bool, expected_valid: bool
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("acc_test", "secret_test")
