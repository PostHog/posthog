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
