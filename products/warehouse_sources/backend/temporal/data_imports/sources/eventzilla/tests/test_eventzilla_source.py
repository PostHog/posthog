import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.source import EventzillaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventzilla import (
    EventzillaSourceConfig,
)


class TestEventzillaSourceClass:
    def setup_method(self) -> None:
        self.source = EventzillaSource()

    @pytest.mark.parametrize("valid,expected", [(True, (True, None)), (False, (False, "Invalid Eventzilla API key"))])
    def test_validate_credentials(self, valid: bool, expected: tuple[bool, str | None]) -> None:
        config = EventzillaSourceConfig(api_key="key")
        status = 200 if valid else 401
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            assert self.source.validate_credentials(config, team_id=1) == expected
        assert network.requests_log[0].path == "/api/v2/events"
