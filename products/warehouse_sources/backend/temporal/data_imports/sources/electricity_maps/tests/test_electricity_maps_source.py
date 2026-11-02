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

    @pytest.mark.parametrize("pricing_nodes", [None, " , "])
    def test_rejects_locational_marginal_price_schema_without_pricing_nodes(self, pricing_nodes: str | None) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="DE", pricing_nodes=pricing_nodes)
        with scripted_network([]) as network:
            is_valid, message = ElectricityMapsSource().validate_credentials(
                config, team_id=1, schema_name="locational_marginal_price_day_ahead"
            )

        assert is_valid is False
        assert message is not None and "pricing node" in message
        assert network.requests_log == []

    @pytest.mark.parametrize(("pricing_nodes", "expected_blocked"), [(None, True), ("CORTINA_1_N106", False)])
    def test_schema_picker_flags_locational_marginal_price_without_pricing_nodes(
        self, pricing_nodes: str | None, expected_blocked: bool
    ) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="DE", pricing_nodes=pricing_nodes)

        permissions = ElectricityMapsSource().get_endpoint_permissions(
            config, team_id=1, endpoints=["carbon_intensity", "locational_marginal_price_day_ahead"]
        )

        assert permissions["carbon_intensity"] is None
        assert (permissions["locational_marginal_price_day_ahead"] is not None) is expected_blocked

    def test_delegates_normalized_zones_to_the_api_probe(self) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="de, dk-dk1")
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=200)]) as network:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert (is_valid, message) == (True, None)
        assert [request.param("zone") for request in network.requests_log] == ["DE", "DK-DK1"]
        assert [request.headers["auth-token"] for request in network.requests_log] == ["token", "token"]
