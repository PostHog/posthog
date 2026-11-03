from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zep import ZepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.source import ZepSource


class TestZepSource:
    def setup_method(self) -> None:
        self.source = ZepSource()
        self.team_id = 7

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zep API key"))])
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: tuple[bool, str | None]) -> None:
        config = ZepSourceConfig(api_key="z_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zep.source.validate_zep_credentials",
            return_value=probe_ok,
        ):
            assert self.source.validate_credentials(config, self.team_id) == expected
