from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import (
    COURIER_API_VERSION_2_0_0,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.source import CourierSource


def _config(api_key: str = "sk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestSourceConfig:
    def test_supports_legacy_and_2_0_0_with_2_0_0_default(self) -> None:
        # 2.0.0 is Courier's current API reference and the new default for new sources; the legacy
        # placeholder stays supported so existing pinned rows keep resolving to the same unversioned
        # wire behaviour (Courier's API has no version header/path, so both labels hit one API).
        source = CourierSource()
        assert source.supported_versions == (UNVERSIONED_API_VERSION, COURIER_API_VERSION_2_0_0)
        assert source.default_version == COURIER_API_VERSION_2_0_0


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in CourierSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only Messages (enqueued_after) has a genuine server-side timestamp filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {"Messages"}
        assert [f["field"] for f in schemas["Messages"].incremental_fields] == ["enqueued"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert CourierSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in CourierSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["Brands"]["sync_methods"] == ["Full refresh"]
        assert "Incremental" in tables["Messages"]["sync_methods"]
