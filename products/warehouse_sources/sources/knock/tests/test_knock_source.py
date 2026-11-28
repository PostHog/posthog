from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.sources.knock.source import KnockSource


def _config(**keys: str | None) -> Any:
    config = MagicMock()
    config.api_key = "sk_test"
    config.object_collections = keys.get("object_collections")
    config.audience_keys = keys.get("audience_keys")
    config.in_app_feed_channel_ids = keys.get("in_app_feed_channel_ids")
    config.service_token = keys.get("service_token")
    return config


class TestGetSchemas:
    @parameterized.expand(
        [
            ("objects", "object_collections", None, False),
            ("objects", "object_collections", "", False),
            ("objects", "object_collections", "accounts", True),
            ("audience_members", "audience_keys", None, False),
            ("audience_members", "audience_keys", " , ", False),
            ("audience_members", "audience_keys", "beta", True),
            ("user_feed_items", "in_app_feed_channel_ids", None, False),
            ("user_feed_items", "in_app_feed_channel_ids", "chan-1", True),
            ("workflows", "service_token", None, False),
            ("channels", "service_token", "", False),
            ("audiences", "service_token", "knock_st_test", True),
            ("audit_logs", "service_token", "knock_st_test", True),
        ]
    )
    def test_keyed_table_syncs_by_default_only_once_keys_are_configured(
        self, table: str, field: str, keys: str | None, expected: bool
    ) -> None:
        config = _config(**{field: keys})
        schemas = {s.name: s for s in KnockSource().get_schemas(config, 1)}
        assert schemas[table].should_sync_default is expected
