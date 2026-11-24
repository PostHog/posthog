from posthog.test.base import APIBaseTest

from products.mcp_analytics.backend.models import MCPAnalyticsSubmission
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPAnalyticsSubmissionModel(APIBaseTest):
    def test_defaults_blank_fields(self) -> None:
        submission = MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="understand MCP usage",
            summary="Feedback entry",
        )

        assert submission.category == ""
        assert submission.blocked is None
        assert submission.attempted_tool == ""
        assert submission.mcp_session_id == ""


class TestMCPIntentTopicRegistry(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def test_round_trips_a_float32_centroid(self) -> None:
        import numpy as np

        from products.mcp_analytics.backend.models import MCPIntentTopic

        centroid = np.linspace(-1.0, 1.0, 256, dtype=np.float32)
        topic = MCPIntentTopic.objects.create(
            team=self.team, label="Create insights", centroid=MCPIntentTopic.encode_centroid(centroid)
        )

        reloaded = MCPIntentTopic.objects.get(pk=topic.pk)
        np.testing.assert_array_equal(reloaded.decoded_centroid(), centroid)
        assert reloaded.status == MCPIntentTopic.Status.ACTIVE
        assert reloaded.first_seen_at is not None
        assert reloaded.last_seen_at is not None

    def test_active_manager_excludes_archived_topics(self) -> None:
        from products.mcp_analytics.backend.models import MCPIntentTopic

        active = MCPIntentTopic.objects.create(team=self.team, label="A", centroid=b"")
        MCPIntentTopic.objects.create(team=self.team, label="B", centroid=b"", status=MCPIntentTopic.Status.ARCHIVED)

        assert list(MCPIntentTopic.active.filter(team=self.team)) == [active]
        assert list(MCPIntentTopic.active.for_team(self.team.pk)) == [active]
        assert list(MCPIntentTopic.active.unscoped().filter(team=self.team)) == [active]
        assert MCPIntentTopic.objects.filter(team=self.team).count() == 2

    def test_run_records_window_and_counts(self) -> None:
        from products.mcp_analytics.backend.models import MCPIntentClusteringRun

        run = MCPIntentClusteringRun.objects.create(
            team=self.team,
            run_id="refit-2026-10-20",
            kind=MCPIntentClusteringRun.Kind.REFIT,
            status=MCPIntentClusteringRun.Status.RUNNING,
        )
        run.status = MCPIntentClusteringRun.Status.SUCCEEDED
        run.n_intents = 20_000
        run.n_topics = 42
        run.n_outliers = 300
        run.save()

        reloaded = MCPIntentClusteringRun.objects.get(pk=run.pk)
        assert reloaded.kind == "refit"
        assert reloaded.status == "succeeded"
        assert (reloaded.n_intents, reloaded.n_topics, reloaded.n_outliers) == (20_000, 42, 300)
        assert reloaded.error_message == ""
