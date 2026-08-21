from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.source import CampfireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campfire import (
    CampfireSourceConfig,
)


class TestCampfireSource:
    def setup_method(self) -> None:
        self.source = CampfireSource()

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Campfire API key"))])
    def test_validate_credentials_maps_transport_result(
        self, _name: str, transport_result: bool, expected: tuple
    ) -> None:
        with patch.object(source_module, "validate_campfire_credentials", return_value=transport_result) as mock:
            result = self.source.validate_credentials(CampfireSourceConfig(api_key="k"), team_id=1)
        assert result == expected
        mock.assert_called_once_with("k", path=None)

    def test_validate_credentials_probes_the_schema_endpoint(self) -> None:
        with patch.object(source_module, "validate_campfire_credentials", return_value=True) as mock:
            self.source.validate_credentials(CampfireSourceConfig(api_key="k"), team_id=1, schema_name="contracts")
        mock.assert_called_once_with("k", path="/rr/api/v1/contracts")
