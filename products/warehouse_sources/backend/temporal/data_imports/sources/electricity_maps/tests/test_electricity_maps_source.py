import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source import (
    ElectricityMapsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source"
    ".validate_electricity_maps_credentials"
)


class TestElectricityMapsCredentialValidation:
    @pytest.mark.parametrize("zones", ["", " , ,"])
    def test_rejects_empty_zone_list_without_calling_the_api(self, zones: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "zone" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("zones", "malformed"),
        [
            ("DE, https://example.com", "HTTPS://EXAMPLE.COM"),
            ("DE DE", "DE DE"),
        ],
    )
    def test_rejects_malformed_zones_without_calling_the_api(self, zones: str, malformed: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and malformed in message
        mock_validate.assert_not_called()

    def test_delegates_normalized_zones_to_the_api_probe(self) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="de, dk-dk1")
        with patch(_VALIDATE, return_value=(True, None)) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert (is_valid, message) == (True, None)
        mock_validate.assert_called_once_with("token", ["DE", "DK-DK1"])
