from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprig import SprigSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source import SprigSource


def _config() -> SprigSourceConfig:
    return SprigSourceConfig(api_key="sprig-key")


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source.validate_sprig_credentials")
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = SprigSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.sprig.com/v2/environments"),
            ("forbidden_after_redirect", "403 Client Error: Forbidden for url: https://sprig.com"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _label: str, observed_error: str) -> None:
        assert any(key in observed_error for key in SprigSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.sprig.com/v2/studies"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.sprig.com/v2/studies"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _label: str, other_error: str) -> None:
        assert not any(key in other_error for key in SprigSource().get_non_retryable_errors())
