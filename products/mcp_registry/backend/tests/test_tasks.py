from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.mcp_registry.backend.tasks.tasks import is_pipeline_enabled, run_mcp_registry_sync


class TestPipelineGate(BaseTest):
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_self_hosted_is_off_without_evaluating_the_flag(self, feature_enabled: MagicMock) -> None:
        with self.is_cloud(False):
            self.assertFalse(is_pipeline_enabled())
        feature_enabled.assert_not_called()

    @patch("posthoganalytics.feature_enabled")
    def test_cloud_follows_the_flag_and_fails_closed(self, feature_enabled: MagicMock) -> None:
        with self.is_cloud(True):
            feature_enabled.return_value = True
            self.assertTrue(is_pipeline_enabled())

            feature_enabled.return_value = False
            self.assertFalse(is_pipeline_enabled())

            # A disabled analytics client (OPT_OUT_CAPTURE) returns None rather than a bool.
            feature_enabled.return_value = None
            self.assertFalse(is_pipeline_enabled())

            feature_enabled.side_effect = RuntimeError("flag service unreachable")
            self.assertFalse(is_pipeline_enabled())

    @patch("products.mcp_registry.backend.tasks.tasks.run_sync_pipeline")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_scheduled_task_skips_the_pipeline_when_self_hosted(
        self, feature_enabled: MagicMock, run_sync_pipeline: MagicMock
    ) -> None:
        with self.is_cloud(False):
            run_mcp_registry_sync()
        run_sync_pipeline.assert_not_called()
        feature_enabled.assert_not_called()

    @patch("products.mcp_registry.backend.tasks.tasks.run_sync_pipeline")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_scheduled_task_runs_the_pipeline_on_cloud_when_flag_is_on(
        self, feature_enabled: MagicMock, run_sync_pipeline: MagicMock
    ) -> None:
        with self.is_cloud(True):
            run_mcp_registry_sync()
        run_sync_pipeline.assert_called_once_with()
