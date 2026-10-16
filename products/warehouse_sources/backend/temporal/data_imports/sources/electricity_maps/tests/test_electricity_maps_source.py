import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source import (
    ElectricityMapsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)


class TestElectricityMapsCredentialValidation:
    @pytest.mark.parametrize("zones", ["", " , ,"])
    def test_rejects_empty_zone_list_without_calling_the_api(self, zones: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with scripted_network([]) as network:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "zone" in message
        assert network.requests_log == []

    @pytest.mark.parametrize(
        ("zones", "malformed"),
        [
            ("DE, https://example.com", "HTTPS://EXAMPLE.COM"),
            ("DE DE", "DE DE"),
        ],
    )
    def test_rejects_malformed_zones_without_calling_the_api(self, zones: str, malformed: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with scripted_network([]) as network:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and malformed in message
        assert network.requests_log == []

    def test_delegates_normalized_zones_to_the_api_probe(self) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="de, dk-dk1")
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=200)]) as network:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert (is_valid, message) == (True, None)
        assert [request.param("zone") for request in network.requests_log] == ["DE", "DK-DK1"]
        assert [request.headers["auth-token"] for request in network.requests_log] == ["token", "token"]
