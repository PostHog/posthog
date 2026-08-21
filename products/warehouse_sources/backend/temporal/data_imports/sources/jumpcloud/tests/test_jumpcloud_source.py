from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource


def _config(api_key: str = "key", org_id: str | None = None, region: str = "us") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.org_id = org_id
    config.region = region
    return config


class TestGetSchemas:
    def test_only_events_is_incremental(self) -> None:
        schemas = {s.name: s for s in JumpcloudSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas["events"].supports_incremental is True
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["timestamp"]
        # The start_time boundary can re-return the watermark row, so append would duplicate it.
        assert all(not s.supports_append for s in schemas.values())
        # The REST entity endpoints have no server-side "updated since" filter.
        assert all(not schema.supports_incremental for name, schema in schemas.items() if name != "events")
