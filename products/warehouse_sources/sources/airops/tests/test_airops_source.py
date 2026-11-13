from parameterized import parameterized

from products.warehouse_sources.sources.airops._config import AirOpsSourceConfig
from products.warehouse_sources.sources.airops.source import AirOpsSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


def _config(api_key: str = "test-key") -> AirOpsSourceConfig:
    return AirOpsSourceConfig.from_dict({"api_key": api_key})


class TestAirOpsSource:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid AirOps API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=200 if probe_result else 401)]) as network:
            assert AirOpsSource().validate_credentials(_config(), team_id=1) == expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
