from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource


def _config(api_key: str = "sk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in KnockSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only messages (inserted_at[gte]) and workflow_recipient_runs (starting_at)
        # have a genuine server-side timestamp filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {
            "messages",
            "workflow_recipient_runs",
        }
        assert [f["field"] for f in schemas["messages"].incremental_fields] == ["inserted_at"]
        assert [f["field"] for f in schemas["workflow_recipient_runs"].incremental_fields] == ["inserted_at"]
