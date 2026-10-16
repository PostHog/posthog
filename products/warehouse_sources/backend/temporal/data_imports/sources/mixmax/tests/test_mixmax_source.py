from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixmax import MixMaxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source import MixMaxSource


def _config() -> MixMaxSourceConfig:
    return MixMaxSourceConfig(api_key="tok")


class TestValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Mixmax API token"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=200 if probe_result else 401)]) as network:
            assert MixMaxSource().validate_credentials(_config(), team_id=1) == expected
        assert [request.path for request in network.requests_log] == ["/v1/users/me"]
        assert network.requests_log[0].headers["x-api-token"] == "tok"
        assert network.session_options[0]["redact_values"] == ("tok",)


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.mixmax.com/v1/sequences?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.mixmax.com/v1/messages?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = MixMaxSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.mixmax.com/v1/sequences"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.mixmax.com/v1/sequences"),
            ("read_timeout", "HTTPSConnectionPool(host='api.mixmax.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = MixMaxSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)
