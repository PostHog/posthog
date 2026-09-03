from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hubplanner import (
    HubplannerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.source import HubplannerSource


class TestHubplannerSource:
    def setup_method(self) -> None:
        self.source = HubplannerSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    def test_validate_credentials_success(self) -> None:
        config = HubplannerSourceConfig(api_key="good")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=True):
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        config = HubplannerSourceConfig(api_key="bad")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=False):
            valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None
