import pytest

from products.warehouse_sources.sources.statuspage._config import StatuspageSourceConfig
from products.warehouse_sources.sources.statuspage.settings import ENDPOINTS
from products.warehouse_sources.sources.statuspage.source import StatuspageSource


class TestStatuspageSource:
    def setup_method(self):
        self.source = StatuspageSource()
        self.team_id = 123

    def test_get_schemas_returns_all_endpoints_as_full_refresh(self):
        schemas = self.source.get_schemas(StatuspageSourceConfig(api_key="key"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No server-side timestamp filter exists, so every schema is full-refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    @pytest.mark.parametrize(
        "schema_name, expected",
        [
            ("pages", True),
            ("components", True),
            ("component_uptime", False),
            ("component_group_uptime", False),
            ("page_access_user_components", False),
            (None, True),
        ],
    )
    def test_resume_covers_only_endpoints_that_save_state(self, schema_name, expected):
        assert self.source.resume_covers_run(incremental_or_append=False, schema_name=schema_name) is expected
