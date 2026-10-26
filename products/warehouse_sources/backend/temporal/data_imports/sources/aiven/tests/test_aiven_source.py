from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.source import AivenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aiven import AivenSourceConfig


def _config() -> AivenSourceConfig:
    return AivenSourceConfig.from_dict({"api_token": "tok"})


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True)])
    def test_maps_validation_result(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, error = AivenSource().validate_credentials(_config(), team_id=1)

        assert ok is expected
        assert (error is None) is expected
        assert [request.path for request in network.requests_log] == ["/v1/me"]
