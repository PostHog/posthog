from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from products.mcp_registry.backend.crawl import crawl_official_registry, upsert_registry_entries
from products.mcp_registry.backend.models import MCPRegistryServer


def _wrapper(name: str, published_at: str = "2026-01-01T00:00:00Z", **server: Any) -> dict[str, Any]:
    return {
        "server": {"name": name, "description": "", **server},
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "publishedAt": published_at}},
    }


def _page(servers: list[dict[str, Any]], next_cursor: str | None = None) -> Mock:
    response = Mock()
    response.json.return_value = {"servers": servers, "metadata": {"nextCursor": next_cursor}}
    response.raise_for_status.return_value = None
    return response


def _raw_entry(name: str, published_at: str = "2026-01-01T00:00:00Z", **server: Any) -> dict[str, Any]:
    entry = _wrapper(name, published_at, **server)["server"]
    entry["_registry_meta"] = {"status": "active", "publishedAt": published_at}
    return entry


class TestCrawl(BaseTest):
    @patch("products.mcp_registry.backend.crawl.requests.get")
    def test_crawl_paginates_and_skips_inactive_entries(self, mock_get: Mock) -> None:
        deleted = _wrapper("io.example/gone")
        deleted["_meta"]["io.modelcontextprotocol.registry/official"]["status"] = "deleted"
        mock_get.side_effect = [
            _page([_wrapper("io.example/one", title="One")], next_cursor="cursor-1"),
            _page(
                [
                    _wrapper(
                        "io.example/two", remotes=[{"type": "streamable-http", "url": "https://two.example.com/mcp"}]
                    ),
                    deleted,
                ]
            ),
        ]

        created, updated = crawl_official_registry()

        assert (created, updated) == (2, 0)
        assert set(MCPRegistryServer.objects.values_list("registry_name", flat=True)) == {
            "io.example/one",
            "io.example/two",
        }
        two = MCPRegistryServer.objects.get(registry_name="io.example/two")
        assert two.canonical_url == "https://two.example.com/mcp"
        assert two.liveness == "unprobed"
        assert MCPRegistryServer.objects.get(registry_name="io.example/one").liveness == "package_only"

    def test_upsert_keeps_newest_version_per_name(self) -> None:
        upsert_registry_entries(
            [
                _raw_entry("io.example/dup", published_at="2026-02-01T00:00:00Z", description="newer"),
                _raw_entry("io.example/dup", published_at="2026-01-01T00:00:00Z", description="older"),
            ]
        )

        assert MCPRegistryServer.objects.get(registry_name="io.example/dup").description == "newer"

    def test_recrawl_refreshes_content_but_not_operational_state(self) -> None:
        server = MCPRegistryServer.objects.create(
            registry_name="io.example/kept",
            display_name="Kept",
            listed_in_registry=True,
            liveness="alive_open",
            auth_method="none",
            is_measured=True,
        )

        created, updated = upsert_registry_entries([_raw_entry("io.example/kept", description="fresh description")])

        server.refresh_from_db()
        assert (created, updated) == (0, 1)
        assert server.description == "fresh description"
        assert server.liveness == "alive_open"
        assert server.is_measured is True
