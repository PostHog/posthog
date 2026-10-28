from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.roark import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.source import RoarkSource


class TestRoarkSource:
    def setup_method(self) -> None:
        self.source = RoarkSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand([(200, True, None)])
    def test_validate_credentials(self, status: int, expected_ok: bool, expected_msg: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            ok, msg = self.source.validate_credentials(RoarkSourceConfig(api_key="k"), self.team_id)
        assert ok is expected_ok
        assert msg == expected_msg
        assert network.requests_log[0].headers["authorization"] == "Bearer k"
