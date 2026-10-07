from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource


def _config(api_key: str = "sk_test", object_collections: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.object_collections = object_collections
    return config


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in KnockSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only messages (inserted_at[gte]) and workflow_recipient_runs (starting_at)
        # have a genuine server-side timestamp filter; the message fan-outs ride the
        # messages filter on their parent walk.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {
            "messages",
            "workflow_recipient_runs",
            "message_events",
            "message_delivery_logs",
        }
        assert [f["field"] for f in schemas["messages"].incremental_fields] == ["inserted_at"]
        assert [f["field"] for f in schemas["workflow_recipient_runs"].incremental_fields] == ["inserted_at"]
        assert [f["field"] for f in schemas["message_events"].incremental_fields] == ["message_inserted_at"]

    @parameterized.expand([(None, False), ("", False), ("accounts", True)])
    def test_objects_syncs_by_default_only_once_collections_are_configured(
        self, object_collections: str | None, expected: bool
    ) -> None:
        schemas = {s.name: s for s in KnockSource().get_schemas(_config(object_collections=object_collections), 1)}
        assert schemas["objects"].should_sync_default is expected

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert KnockSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in KnockSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["users"]["sync_methods"] == ["Full refresh"]
        assert "Incremental" in tables["messages"]["sync_methods"]
