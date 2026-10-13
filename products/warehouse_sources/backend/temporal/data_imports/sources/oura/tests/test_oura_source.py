from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.oura import source as oura_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.source import OuraSource


def _config(token: str = "tok") -> Any:
    return OuraSource().parse_config({"access_token": token})


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_is_rejected", 403, "daily_sleep", False),
            ("transport_failure", -1, None, False),
        ]
    )
    def test_validation(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(oura_source_module, "probe_endpoint", return_value=status):
            ok, error = OuraSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        if expected_ok:
            assert error is None
        else:
            assert error is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.ouraring.com/v2/usercollection/sleep",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.ouraring.com/v2/usercollection/heartrate"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OuraSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.ouraring.com"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.ouraring.com"),
            ("read_timeout", "HTTPSConnectionPool(host='api.ouraring.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OuraSource().get_non_retryable_errors()
        assert not any(key in observed for key in non_retryable)
