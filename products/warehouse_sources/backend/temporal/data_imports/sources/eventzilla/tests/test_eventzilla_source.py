import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.source import EventzillaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventzilla import (
    EventzillaSourceConfig,
)


class TestEventzillaSourceClass:
    def setup_method(self) -> None:
        self.source = EventzillaSource()

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["events", "attendees"])
        assert {s.name for s in schemas} == {"events", "attendees"}

    @pytest.mark.parametrize("valid,expected", [(True, (True, None)), (False, (False, "Invalid Eventzilla API key"))])
    def test_validate_credentials(self, valid: bool, expected: tuple[bool, str | None]) -> None:
        config = EventzillaSourceConfig(api_key="key")
        with patch.object(source_module, "validate_eventzilla_credentials", return_value=valid):
            assert self.source.validate_credentials(config, team_id=1) == expected
