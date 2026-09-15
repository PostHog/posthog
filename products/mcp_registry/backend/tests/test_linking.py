from posthog.test.base import BaseTest

from products.mcp_registry.backend.linking import resolve_measured_server
from products.mcp_registry.backend.models import MCPRegistryServer


def _registry_server(registry_name: str, display_name: str) -> MCPRegistryServer:
    return MCPRegistryServer.objects.create(
        registry_name=registry_name, display_name=display_name, listed_in_registry=True
    )


class TestLinking(BaseTest):
    def test_override_beats_name_collision_with_repackage(self) -> None:
        # "PostHog" name-matches both the official server and a third-party repackage;
        # the curated override must pick the official one.
        _registry_server("com.thirdparty/posthog", "posthog")
        official = _registry_server("io.github.PostHog/mcp", "PostHog MCP Server")

        resolution = resolve_measured_server("PostHog")

        assert resolution.server == official
        assert resolution.link_method == "override"
        assert resolution.link_candidates == []
        official.refresh_from_db()
        assert official.is_measured is True

    def test_ambiguous_name_becomes_standalone_with_candidates(self) -> None:
        _registry_server("io.example/acme", "Acme")
        _registry_server("com.acme/mcp", "acme")

        resolution = resolve_measured_server("Acme")

        assert resolution.server.listed_in_registry is False
        assert resolution.link_method == "standalone"
        assert set(resolution.link_candidates) == {"io.example/acme", "com.acme/mcp"}

    def test_single_exact_match_links(self) -> None:
        match = _registry_server("io.example/linear", "Linear")
        _registry_server("io.example/linear-docs", "Linear docs helper")

        resolution = resolve_measured_server("Linear")

        assert resolution.server == match
        assert resolution.link_method == "exact_name"
        assert resolution.link_candidates == []

    def test_standalone_row_is_reused_across_runs(self) -> None:
        first = resolve_measured_server("Internal Tools")
        second = resolve_measured_server("Internal Tools")

        assert first.server == second.server
        assert MCPRegistryServer.objects.filter(display_name="Internal Tools").count() == 1

    def test_template_default_name_resolves_to_no_server(self) -> None:
        resolution = resolve_measured_server("mcp-typescript server on vercel")

        assert resolution.server is None
        assert resolution.link_method == "template_default"
        # No shared global row is created for a name many projects' scaffolds advertise.
        assert MCPRegistryServer.objects.filter(display_name="mcp-typescript server on vercel").count() == 0

    def test_template_default_matching_is_normalized(self) -> None:
        for name in ("MCP Server", "mcp-server", "  server  "):
            resolution = resolve_measured_server(name)
            assert resolution.server is None, name
            assert resolution.link_method == "template_default", name

    def test_non_default_name_still_creates_standalone(self) -> None:
        resolution = resolve_measured_server("Acme Internal Tools")

        assert resolution.server is not None
        assert resolution.link_method == "standalone"
