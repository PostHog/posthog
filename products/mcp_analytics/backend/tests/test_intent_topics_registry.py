import numpy as np

from products.mcp_analytics.backend.intent_topics.topic_registry import (
    ExistingTopic,
    MatchResult,
    match_clusters_to_topics,
)


def _unit(v: list[float]) -> np.ndarray:
    arr = np.asarray(v, dtype=np.float32)
    return arr / np.linalg.norm(arr)


class TestMatchClustersToTopics:
    def test_reuses_the_topic_id_above_the_threshold(self) -> None:
        existing = [ExistingTopic(id="t1", centroid=_unit([1, 0, 0]))]
        clusters = np.stack([_unit([0.98, 0.1, 0])])

        result = match_clusters_to_topics(clusters, cluster_sizes=[10], existing=existing, threshold=0.85)

        assert result == MatchResult(reused={0: "t1"}, created=[], unmatched_topics=[])

    def test_creates_a_topic_below_the_threshold(self) -> None:
        existing = [ExistingTopic(id="t1", centroid=_unit([1, 0, 0]))]
        clusters = np.stack([_unit([0, 1, 0])])

        result = match_clusters_to_topics(clusters, cluster_sizes=[10], existing=existing, threshold=0.85)

        assert result == MatchResult(reused={}, created=[0], unmatched_topics=["t1"])

    def test_two_clusters_one_topic_best_similarity_wins(self) -> None:
        existing = [ExistingTopic(id="t1", centroid=_unit([1, 0, 0]))]
        clusters = np.stack([_unit([0.9, 0.3, 0]), _unit([0.99, 0.05, 0])])

        result = match_clusters_to_topics(clusters, cluster_sizes=[50, 10], existing=existing, threshold=0.85)

        assert result.reused == {1: "t1"}
        assert result.created == [0]
        assert result.unmatched_topics == []

    def test_each_topic_is_used_at_most_once_and_unmatched_topics_are_listed(self) -> None:
        existing = [
            ExistingTopic(id="t1", centroid=_unit([1, 0, 0])),
            ExistingTopic(id="t2", centroid=_unit([0, 1, 0])),
            ExistingTopic(id="t3", centroid=_unit([0, 0, 1])),
        ]
        clusters = np.stack([_unit([0, 0.97, 0.1]), _unit([0.97, 0.1, 0])])

        result = match_clusters_to_topics(clusters, cluster_sizes=[5, 5], existing=existing, threshold=0.85)

        assert result.reused == {0: "t2", 1: "t1"}
        assert result.created == []
        assert result.unmatched_topics == ["t3"]

    def test_ties_resolve_deterministically_by_cluster_size_then_index(self) -> None:
        existing = [ExistingTopic(id="t1", centroid=_unit([1, 0, 0]))]
        clusters = np.stack([_unit([1, 0, 0]), _unit([1, 0, 0])])

        bigger_second = match_clusters_to_topics(clusters, cluster_sizes=[5, 50], existing=existing)
        equal = match_clusters_to_topics(clusters, cluster_sizes=[5, 5], existing=existing)

        assert bigger_second.reused == {1: "t1"}
        assert equal.reused == {0: "t1"}

    def test_no_existing_topics_creates_everything(self) -> None:
        clusters = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0])])

        result = match_clusters_to_topics(clusters, cluster_sizes=[1, 1], existing=[])

        assert result == MatchResult(reused={}, created=[0, 1], unmatched_topics=[])
