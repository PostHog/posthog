import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.source import DeelSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deel import DeelSourceConfig


class TestDeelSource:
    def setup_method(self):
        self.source = DeelSource()
        self.team_id = 123
        self.config = DeelSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "api_version, dated_tables_listed",
        [
            ("v2", False),
            ("2026-01-01", True),
            # No pin is a source being created, which lands on the default version.
            (None, True),
        ],
    )
    def test_get_schemas_lists_dated_tables_only_on_the_dated_pin(self, api_version, dated_tables_listed):
        dated_tables = {"it_seats", "it_clearance_requests", "time_off_policies", "equity_awards"}

        names = {schema.name for schema in self.source.get_schemas(self.config, self.team_id, api_version=api_version)}

        assert names == (set(ENDPOINTS) if dated_tables_listed else set(ENDPOINTS) - dated_tables)
