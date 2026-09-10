from unittest.mock import patch

from django.test import SimpleTestCase

from products.mcp_registry.backend.constants import MCP_REGISTRY_PIPELINE_DISTINCT_ID
from products.mcp_registry.backend.tasks.tasks import run_sync_pipeline


class TestSyncPipelineHeartbeat(SimpleTestCase):
    @patch("products.mcp_registry.backend.tasks.tasks.posthoganalytics.capture")
    @patch("products.mcp_registry.backend.tasks.tasks.compute_ranking_run")
    @patch("products.mcp_registry.backend.tasks.tasks.probe_stalest_servers", return_value=500)
    @patch("products.mcp_registry.backend.tasks.tasks.aggregate_measured_servers", return_value=604)
    @patch("products.mcp_registry.backend.tasks.tasks.crawl_official_registry")
    def test_sweep_emits_a_heartbeat_event(self, _crawl, _aggregate, _probe, _rank, capture) -> None:
        # The daily run once vanished with no error and no trace; the heartbeat is what
        # turns "no run happened" into something an alert can see.
        run_sync_pipeline()

        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        assert kwargs["distinct_id"] == MCP_REGISTRY_PIPELINE_DISTINCT_ID
        assert kwargs["event"] == "mcp_registry_sync_completed"
        assert kwargs["properties"]["probed"] == 500
        assert kwargs["properties"]["measured_sources"] == 604

    @patch("products.mcp_registry.backend.tasks.tasks.posthoganalytics.capture", side_effect=Exception("down"))
    @patch("products.mcp_registry.backend.tasks.tasks.compute_ranking_run")
    @patch("products.mcp_registry.backend.tasks.tasks.probe_stalest_servers", return_value=0)
    @patch("products.mcp_registry.backend.tasks.tasks.aggregate_measured_servers", return_value=0)
    @patch("products.mcp_registry.backend.tasks.tasks.crawl_official_registry")
    def test_heartbeat_failure_does_not_sink_the_sweep(self, _crawl, _aggregate, _probe, _rank, _capture) -> None:
        outcome = run_sync_pipeline()

        assert outcome["probed"] == 0
