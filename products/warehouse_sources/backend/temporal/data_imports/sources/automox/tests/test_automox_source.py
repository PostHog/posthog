from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.source import AutomoxSource


def _config(api_key: str = "key", organization_id: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.organization_id = organization_id
    return config


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in AutomoxSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only events (startDate) and policy_runs (start_time) have a server-side time filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {"events", "policy_runs"}
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["create_time"]
        assert [f["field"] for f in schemas["policy_runs"].incremental_fields] == ["run_time"]
        # Fan-out style composite keys where uniqueness beyond the parent is undocumented.
        assert schemas["packages"].detected_primary_keys == ["id", "server_id"]
        assert schemas["policy_runs"].detected_primary_keys == ["policy_uuid", "execution_token"]
