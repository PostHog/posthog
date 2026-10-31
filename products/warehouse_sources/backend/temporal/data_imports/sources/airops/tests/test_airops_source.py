from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.airops.source import AirOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airops import AirOpsSourceConfig


def _config(api_key: str = "test-key") -> AirOpsSourceConfig:
    return AirOpsSourceConfig.from_dict({"api_key": api_key})


class TestAirOpsSource:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid AirOps API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=200 if probe_result else 401)]) as network:
            assert AirOpsSource().validate_credentials(_config(), team_id=1) == expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
