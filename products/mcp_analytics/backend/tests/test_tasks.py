from posthog.test.base import APIBaseTest
from unittest.mock import patch

import numpy as np

from products.mcp_analytics.backend import intent_clustering
from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot
from products.mcp_analytics.backend.tasks import tasks
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestComputeIntentClusters(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def _stub_corpus(self) -> list[intent_clustering.IntentRecord]:
        return [
            intent_clustering.IntentRecord(
                intent_text="check feature flag rollout",
                frequency=10,
                tool_counts={"feature_flag_get": 10},
                error_counts={},
            ),
            intent_clustering.IntentRecord(
                intent_text="look up feature flag status",
                frequency=4,
                tool_counts={"feature_flag_get": 4},
                error_counts={},
            ),
        ]

    def _stub_embeddings(self) -> tuple[np.ndarray, list[int]]:
        # Two near-identical unit vectors so they cluster together.
        vectors = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.99, 0.05, 0.0],
            ],
            dtype=np.float32,
        )
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors, [0, 1]

    def test_writes_snapshot_on_success(self) -> None:
        with (
            patch.object(intent_clustering, "fetch_intent_corpus", return_value=(self._stub_corpus(), {})),
            patch.object(intent_clustering, "embed_intents_async") as mock_embed,
            patch.object(intent_clustering, "fetch_session_journeys", return_value={}),
        ):
            # asyncio.run unwraps the coroutine; emulate the awaited result.
            async def fake_embed(team, texts):  # noqa: ARG001
                return self._stub_embeddings()

            mock_embed.side_effect = fake_embed
            tasks.compute_intent_clusters.apply(args=[self.team.id, self.user.id]).get()

        snapshot = MCPIntentClusterSnapshot.objects.get(team=self.team)
        assert snapshot.status == MCPIntentClusterSnapshot.Status.IDLE
        assert snapshot.error_message == ""
        assert snapshot.last_computed_at is not None
        assert snapshot.last_computed_by_id == self.user.id
        assert len(snapshot.clusters["clusters"]) == 1
        assert snapshot.clusters["clusters"][0]["call_count"] == 14

    def test_empty_corpus_writes_empty_snapshot(self) -> None:
        with patch.object(intent_clustering, "fetch_intent_corpus", return_value=([], {})):
            tasks.compute_intent_clusters.apply(args=[self.team.id, self.user.id]).get()

        snapshot = MCPIntentClusterSnapshot.objects.get(team=self.team)
        assert snapshot.status == MCPIntentClusterSnapshot.Status.IDLE
        assert snapshot.clusters["clusters"] == []
        assert snapshot.clusters["computed_with"]["n_intents"] == 0

    def test_records_error_on_failure(self) -> None:
        with patch.object(intent_clustering, "fetch_intent_corpus", side_effect=RuntimeError("boom")):
            try:
                tasks.compute_intent_clusters.apply(args=[self.team.id, self.user.id]).get()
            except Exception:
                # We expect the task to re-raise after marking error and exhausting retries.
                pass

        snapshot = MCPIntentClusterSnapshot.objects.get(team=self.team)
        assert snapshot.status == MCPIntentClusterSnapshot.Status.ERROR
        assert "boom" in snapshot.error_message
