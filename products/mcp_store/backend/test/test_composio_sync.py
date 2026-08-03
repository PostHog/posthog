from django.test import SimpleTestCase

from parameterized import parameterized

from products.mcp_store.backend.catalog import MCP_SERVER_CATALOG
from products.mcp_store.backend.composio import ToolkitInfo
from products.mcp_store.backend.composio_sync import SERVED_ELSEWHERE, _excluded_reason, _icon_domain_for


def _toolkit(slug: str, name: str = "Example", app_url: str = "") -> ToolkitInfo:
    return ToolkitInfo(slug=slug, name=name, description="", categories=(), tools_count=0, app_url=app_url)


class TestComposioSyncDeduplication(SimpleTestCase):
    @parameterized.expand(
        [
            ("www", "https://www.box.com", "box.com"),
            ("about", "https://about.gitlab.com", "gitlab.com"),
            ("console", "https://console.prisma.io", "prisma.io"),
            ("app", "https://app.example.io/path", "example.io"),
            ("bare", "https://asana.com", "asana.com"),
            ("empty", "", ""),
        ]
    )
    def test_icon_domain_strips_marketing_subdomains(self, _name: str, app_url: str, expected: str) -> None:
        assert _icon_domain_for(_toolkit("x", app_url=app_url)) == expected

    @parameterized.expand([(name,) for name in sorted({e.name for e in MCP_SERVER_CATALOG})])
    def test_every_direct_catalog_name_is_excluded(self, catalog_name: str) -> None:
        # A Composio toolkit that shares a name with a server we already serve directly must never
        # ship as a card. Adding a catalog entry whose Composio slug differs is exactly how six
        # duplicates reached the marketplace, so this fails the moment that gap reopens by name.
        assert _excluded_reason(_toolkit("some-slug", name=catalog_name)) is not None

    @parameterized.expand([("lowercase", "notion"), ("uppercase", "NOTION"), ("padded", "  Notion  ")])
    def test_catalog_name_match_ignores_case_and_padding(self, _name: str, supplied_name: str) -> None:
        assert _excluded_reason(_toolkit("notion-x", name=supplied_name)) is not None

    def test_unrelated_toolkit_is_not_excluded(self) -> None:
        assert _excluded_reason(_toolkit("apaleo", name="Apaleo", app_url="https://apaleo.com")) is None

    def test_slug_exclusions_carry_a_reason(self) -> None:
        # The reason is what tells a reviewer why a toolkit is withheld; a blank one is a silent drop.
        assert all(reason for reason in SERVED_ELSEWHERE.values())
