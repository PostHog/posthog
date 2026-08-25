from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource


def _config(api_key: str = "key", org_id: str | None = None, region: str = "us") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.org_id = org_id
    config.region = region
    return config


class TestSourceConfig:
    def test_connection_host_fields_force_secret_reentry_on_retarget(self) -> None:
        # Changing org_id or region retargets the stored API key (different organization's
        # data, or a different regional host), so both must force re-entering the key.
        assert JumpcloudSource().connection_host_fields == ["org_id", "region"]


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

    def test_primary_keys_follow_api_family(self) -> None:
        schemas = {s.name: s for s in JumpcloudSource().get_schemas(_config(), team_id=1)}
        # v1 resources use Mongo-style `_id`; v2 groups and Insights events use `id`.
        assert schemas["users"].detected_primary_keys == ["_id"]
        assert schemas["user_groups"].detected_primary_keys == ["id"]
        assert schemas["events"].detected_primary_keys == ["id"]

    def test_names_filter(self) -> None:
        schemas = JumpcloudSource().get_schemas(_config(), team_id=1, names=["users", "events"])
        assert {s.name for s in schemas} == {"users", "events"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert JumpcloudSource.lists_tables_without_credentials is True
        tables = JumpcloudSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        events = next(t for t in tables if t["name"] == "events")
        assert "Incremental" in events["sync_methods"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized_console",
                "401 Client Error: Unauthorized for url: https://console.jumpcloud.com/api/systemusers?limit=100",
            ),
            (
                "forbidden_insights",
                "403 Client Error: Forbidden for url: https://api.jumpcloud.com/insights/directory/v1/events",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='console.jumpcloud.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://console.jumpcloud.com/api/systems",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://console.jumpcloud.com/api/systemusers",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
