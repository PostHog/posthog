from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource


def _config(api_key: str = "sk_test", object_collections: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.object_collections = object_collections
    return config


class TestGetSchemas:
    @parameterized.expand([(None, False), ("", False), ("accounts", True)])
    def test_objects_syncs_by_default_only_once_collections_are_configured(
        self, object_collections: str | None, expected: bool
    ) -> None:
        schemas = {s.name: s for s in KnockSource().get_schemas(_config(object_collections=object_collections), 1)}
        assert schemas["objects"].should_sync_default is expected
