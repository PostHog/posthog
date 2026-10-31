from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource


def _config(api_key: str = "sk_test", object_collections: str | None = None, audience_keys: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.object_collections = object_collections
    config.audience_keys = audience_keys
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
        ]
    )
    def test_keyed_table_syncs_by_default_only_once_keys_are_configured(
        self, table: str, field: str, keys: str | None, expected: bool
    ) -> None:
        config = _config(object_collections=keys) if field == "object_collections" else _config(audience_keys=keys)
        schemas = {s.name: s for s in KnockSource().get_schemas(config, 1)}
        assert schemas[table].should_sync_default is expected
