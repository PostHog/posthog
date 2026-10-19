from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oura import OuraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.source import OuraSource


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
        script: list[ScriptedResponse | BaseException] = (
            [ConnectionError("connection failed")] if status == -1 else [ScriptedResponse(status=status)]
        )
        with scripted_network(script) as network:
            ok, error = OuraSource().validate_credentials(
                OuraSourceConfig(access_token="tok"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert network.requests_log[0].path == (
            "/v2/usercollection/daily_sleep" if schema_name else "/v2/usercollection/personal_info"
        )
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
