import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source import GleifSource


class TestGleifSource:
    def setup_method(self) -> None:
        self.source = GleifSource()
        self.team_id = 123
        self.config = GleifSourceConfig()

    @pytest.mark.parametrize(("status_code", "expected_valid"), [(200, True), (500, False)])
    def test_validate_credentials(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True
