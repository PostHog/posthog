from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.roark import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.source import RoarkSource


class TestRoarkSource:
    def setup_method(self) -> None:
        self.source = RoarkSource()
        self.team_id = 123

    @parameterized.expand([(True, True, None), (False, False, "Invalid Roark API key")])
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch.object(source_module, "validate_roark_credentials", return_value=valid):
            ok, msg = self.source.validate_credentials(RoarkSourceConfig(api_key="k"), self.team_id)
        assert ok is expected_ok
        assert msg == expected_msg
