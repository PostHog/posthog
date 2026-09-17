from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.mcp_registry.backend.models import MCPRegistryServer


class TestBackfillMCPRegistryProbesCommand(BaseTest):
    def _server(self, name: str) -> MCPRegistryServer:
        return MCPRegistryServer.objects.create(display_name=name, canonical_url=f"https://{name}.example.com/mcp")

    @patch("products.mcp_registry.backend.management.commands.backfill_mcp_registry_probes.probe_stalest_servers")
    def test_limit_zero_probes_nothing(self, mock_probe) -> None:
        self._server("a")

        call_command("backfill_mcp_registry_probes", "--limit", "0")

        mock_probe.assert_not_called()

    @patch("products.mcp_registry.backend.management.commands.backfill_mcp_registry_probes.probe_stalest_servers")
    def test_limit_caps_the_probe_count(self, mock_probe) -> None:
        self._server("a")
        self._server("b")
        self._server("c")
        mock_probe.side_effect = [1, 0]

        call_command("backfill_mcp_registry_probes", "--limit", "1")

        assert mock_probe.call_count == 1
        assert mock_probe.call_args.kwargs["batch_size"] == 1

    @patch("products.mcp_registry.backend.management.commands.backfill_mcp_registry_probes.probe_stalest_servers")
    def test_no_limit_probes_everything_probeable(self, mock_probe) -> None:
        self._server("a")
        self._server("b")
        mock_probe.side_effect = [2, 0]

        call_command("backfill_mcp_registry_probes")

        assert mock_probe.call_args.kwargs["batch_size"] == 2
