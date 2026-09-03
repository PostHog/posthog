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

        server, method, candidates = resolve_measured_server("PostHog")

        assert server == official
        assert method == "override"
        assert candidates == []
        official.refresh_from_db()
        assert official.is_measured is True

    def test_ambiguous_name_becomes_standalone_with_candidates(self) -> None:
        _registry_server("io.example/acme", "Acme")
        _registry_server("com.acme/mcp", "acme")

        server, method, candidates = resolve_measured_server("Acme")

        assert server.listed_in_registry is False
        assert method == "standalone"
        assert set(candidates) == {"io.example/acme", "com.acme/mcp"}

    def test_single_exact_match_links(self) -> None:
        match = _registry_server("io.example/linear", "Linear")
        _registry_server("io.example/linear-docs", "Linear docs helper")

        server, method, candidates = resolve_measured_server("Linear")

        assert server == match
        assert method == "exact_name"
        assert candidates == []

    def test_standalone_row_is_reused_across_runs(self) -> None:
        first, _method, _candidates = resolve_measured_server("Internal Tools")
        second, _method, _candidates = resolve_measured_server("Internal Tools")

        assert first == second
        assert MCPRegistryServer.objects.filter(display_name="Internal Tools").count() == 1
