from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

import numpy as np

from products.mcp_analytics.backend.intent_topics.clustering import FitOutput
from products.mcp_analytics.backend.intent_topics.persist import (
    active_topic_vectors,
    apply_fit,
    existing_topics,
    finish_run,
    latest_pca_basis,
    start_run,
    update_topic_labels,
)
from products.mcp_analytics.backend.intent_topics.topic_registry import MatchResult
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NOW = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


def _unit(axis: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[axis] = 1.0
    return v


def _fit() -> FitOutput:
    # 4 points: two in cluster 0 (axis 0), two in cluster 1 (axis 1)
    return FitOutput(
        labels=np.array([0, 0, 1, 1]),
        centroids=np.stack([_unit(0), _unit(1)]),
        outlier_distances=np.array([0.2, 0.3], dtype=np.float32),
        pca_mean=np.zeros(8, dtype=np.float32),
        pca_components=np.stack([_unit(0), _unit(1)]),
        coords_2d=np.array([[1.0, 0.0], [0.8, 0.1], [0.0, 1.0], [0.1, 0.9]], dtype=np.float32),
    )


class TestApplyFit(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.recent = MCPIntentTopic.objects.create(
            team=self.team, label="Old label", centroid=MCPIntentTopic.encode_centroid(_unit(0) * 0.9)
        )
        self.stale = MCPIntentTopic.objects.create(
            team=self.team, label="Stale", centroid=MCPIntentTopic.encode_centroid(_unit(5))
        )
        MCPIntentTopic.objects.filter(pk=self.stale.pk).update(last_seen_at=NOW - timedelta(days=40))
        self.run = start_run(
            self.team,
            kind=MCPIntentClusteringRun.Kind.REFIT,
            run_id="refit-1",
            window_start=NOW - timedelta(days=7),
            window_end=NOW,
        )

    def test_updates_reused_topics_creates_new_ones_and_archives_stale_ones(self) -> None:
        match = MatchResult(reused={0: str(self.recent.pk)}, created=[1], unmatched_topics=[str(self.stale.pk)])

        result = apply_fit(self.team, run=self.run, fit=_fit(), match=match, now=NOW)

        self.recent.refresh_from_db()
        np.testing.assert_array_equal(self.recent.decoded_centroid(), _unit(0))
        assert self.recent.outlier_distance == np.float32(0.2)
        assert self.recent.member_count == 2
        assert (round(self.recent.centroid_x, 2), round(self.recent.centroid_y, 2)) == (0.9, 0.05)
        assert self.recent.label == "Old label"
        assert self.recent.last_run_id == "refit-1"

        created = MCPIntentTopic.objects.get(pk=result.topic_ids_by_cluster[1])
        assert created.label.startswith("Topic ")
        assert created.member_count == 2
        assert result.created == [str(created.pk)]

        self.stale.refresh_from_db()
        assert self.stale.status == MCPIntentTopic.Status.ARCHIVED
        assert result.archived == [str(self.stale.pk)]

    def test_recently_seen_unmatched_topics_survive(self) -> None:
        MCPIntentTopic.objects.filter(pk=self.stale.pk).update(last_seen_at=NOW - timedelta(days=3))
        match = MatchResult(reused={0: str(self.recent.pk)}, created=[1], unmatched_topics=[str(self.stale.pk)])

        result = apply_fit(self.team, run=self.run, fit=_fit(), match=match, now=NOW)

        self.stale.refresh_from_db()
        assert self.stale.status == MCPIntentTopic.Status.ACTIVE
        assert result.archived == []

    def test_saves_the_pca_basis_on_the_run_and_exposes_vectors(self) -> None:
        match = MatchResult(reused={0: str(self.recent.pk)}, created=[1], unmatched_topics=[str(self.stale.pk)])
        apply_fit(self.team, run=self.run, fit=_fit(), match=match, now=NOW)
        finish_run(self.run, status=MCPIntentClusteringRun.Status.SUCCEEDED, n_topics=2)

        basis = latest_pca_basis(self.team)
        assert basis is not None
        assert basis.pc1 == _unit(0).tolist() and basis.pc2 == _unit(1).tolist()

        vectors = active_topic_vectors(self.team)
        created_id = str(MCPIntentTopic.active.filter(team=self.team).exclude(pk=self.recent.pk).get().pk)
        assert sorted(v.topic_id for v in vectors) == sorted([str(self.recent.pk), created_id])
        assert {v.topic_id: round(v.outlier_distance, 2) for v in vectors}[str(self.recent.pk)] == 0.2

    def test_existing_topics_excludes_archived(self) -> None:
        MCPIntentTopic.objects.filter(pk=self.stale.pk).update(status=MCPIntentTopic.Status.ARCHIVED)

        assert [t.id for t in existing_topics(self.team)] == [str(self.recent.pk)]

    def test_update_topic_labels(self) -> None:
        update_topic_labels(self.team, {str(self.recent.pk): ("Create insights", "Agents build charts.")})

        self.recent.refresh_from_db()
        assert (self.recent.label, self.recent.summary) == ("Create insights", "Agents build charts.")


class TestRunBookkeeping(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def test_start_and_finish(self) -> None:
        run = start_run(
            self.team,
            kind=MCPIntentClusteringRun.Kind.ASSIGN,
            run_id="assign-1",
            window_start=NOW - timedelta(days=1),
            window_end=NOW,
        )
        assert run.status == MCPIntentClusteringRun.Status.RUNNING

        finish_run(run, status=MCPIntentClusteringRun.Status.FAILED, error_message="boom", n_intents=5)

        run.refresh_from_db()
        assert (run.status, run.error_message, run.n_intents) == ("failed", "boom", 5)
        assert run.finished_at is not None

    def test_latest_pca_basis_is_none_without_a_succeeded_refit(self) -> None:
        assert latest_pca_basis(self.team) is None
