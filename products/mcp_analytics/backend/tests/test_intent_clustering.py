"""Tests for the pure functions in intent_clustering.

These tests are intentionally light on Django/ClickHouse and heavy on the
algorithm. They cover the math (clustering, entropy, medoid) and the snapshot
shape we promise the frontend.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

import numpy as np
from parameterized import parameterized

from posthog.temporal.mcp_analytics.summarize_session_intents.activities import NO_INTENT_RECORDED_FALLBACK

from products.mcp_analytics.backend.intent_clustering import (
    DEFAULT_DISTANCE_THRESHOLD,
    IntentRecord,
    _medoid_index,
    _routing_entropy,
    build_snapshot,
    cluster_embeddings,
    fetch_intent_corpus,
)
from products.mcp_analytics.backend.models import MCPSession
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

# Helpers


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


# cluster_embeddings ------------------------------------------------------


class TestClusterEmbeddings:
    def test_returns_empty_array_on_empty_input(self) -> None:
        labels = cluster_embeddings(np.zeros((0, 4), dtype=np.float32))
        assert labels.shape == (0,)

    def test_single_intent_yields_one_label(self) -> None:
        labels = cluster_embeddings(np.array([[1.0, 0.0, 0.0]], dtype=np.float32))
        assert labels.tolist() == [0]

    def test_two_tight_groups_yield_two_clusters(self) -> None:
        # Two well-separated groups in cosine space.
        embeddings = np.array(
            [
                _unit([1.0, 0.0, 0.0]),
                _unit([0.99, 0.05, 0.0]),
                _unit([0.0, 1.0, 0.0]),
                _unit([0.05, 0.99, 0.0]),
            ]
        )
        labels = cluster_embeddings(embeddings, distance_threshold=0.2)
        assert labels[0] == labels[1]
        assert labels[2] == labels[3]
        assert labels[0] != labels[2]

    def test_threshold_zero_makes_every_point_its_own_cluster(self) -> None:
        embeddings = np.array(
            [
                _unit([1.0, 0.0, 0.0]),
                _unit([0.0, 1.0, 0.0]),
                _unit([0.0, 0.0, 1.0]),
            ]
        )
        labels = cluster_embeddings(embeddings, distance_threshold=0.0)
        assert len(set(labels.tolist())) == 3

    def test_high_threshold_collapses_to_one_cluster(self) -> None:
        embeddings = np.array(
            [
                _unit([1.0, 0.0, 0.0]),
                _unit([0.0, 1.0, 0.0]),
                _unit([0.0, 0.0, 1.0]),
            ]
        )
        labels = cluster_embeddings(embeddings, distance_threshold=2.0)
        assert len(set(labels.tolist())) == 1


# _routing_entropy --------------------------------------------------------


class TestRoutingEntropy:
    def test_single_tool_is_zero(self) -> None:
        assert _routing_entropy({"query_run": 10}) == 0.0

    def test_empty_is_zero(self) -> None:
        assert _routing_entropy({}) == 0.0

    def test_perfectly_uniform_is_one(self) -> None:
        assert _routing_entropy({"a": 5, "b": 5}) == pytest.approx(1.0)
        assert _routing_entropy({"a": 1, "b": 1, "c": 1}) == pytest.approx(1.0)

    def test_skewed_distribution_is_between(self) -> None:
        # 90/10 split should be much less than uniform but well above zero.
        value = _routing_entropy({"a": 90, "b": 10})
        assert 0.0 < value < 1.0
        # Sanity-check against Shannon formula directly.
        p = [0.9, 0.1]
        expected = -sum(x * math.log(x) for x in p) / math.log(2)
        assert value == pytest.approx(expected)


# _medoid_index -----------------------------------------------------------


class TestMedoidIndex:
    def test_single_member_returns_itself(self) -> None:
        embeddings = np.array([_unit([1.0, 0.0])])
        assert _medoid_index(embeddings, [0]) == 0

    def test_picks_centermost_member(self) -> None:
        # The middle vector is the centroid of the three; should be the medoid.
        embeddings = np.array(
            [
                _unit([1.0, 0.0]),
                _unit([0.5, 0.5]),  # closer to centroid (sum direction)
                _unit([0.0, 1.0]),
            ]
        )
        assert _medoid_index(embeddings, [0, 1, 2]) == 1


# build_snapshot ----------------------------------------------------------


class TestBuildSnapshot:
    def test_empty_corpus_returns_empty_snapshot(self) -> None:
        snapshot = build_snapshot([], np.array([], dtype=np.int64), np.zeros((0, 4), dtype=np.float32))
        assert snapshot["clusters"] == []
        assert snapshot["computed_with"]["n_clusters"] == 0

    def test_aggregates_tool_counts_across_member_intents(self) -> None:
        records = [
            IntentRecord(
                intent_text="check feature flag rollout",
                frequency=10,
                tool_counts={"feature_flag_get": 8, "query_run": 2},
                error_counts={"feature_flag_get": 1},
            ),
            IntentRecord(
                intent_text="look up feature flag status",
                frequency=4,
                tool_counts={"feature_flag_get": 4},
                error_counts={},
            ),
        ]
        labels = np.array([0, 0], dtype=np.int64)
        embeddings = np.array([_unit([1.0, 0.1]), _unit([1.0, 0.0])], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings)

        assert len(snapshot["clusters"]) == 1
        cluster = snapshot["clusters"][0]
        assert cluster["intent_count"] == 2
        assert cluster["call_count"] == 14
        assert cluster["error_count"] == 1
        # tool_distribution is sorted by count desc
        assert cluster["tool_distribution"][0]["tool"] == "feature_flag_get"
        assert cluster["tool_distribution"][0]["count"] == 12
        assert cluster["tool_distribution"][1]["tool"] == "query_run"
        assert cluster["tool_distribution"][1]["count"] == 2
        # Error rate is per-tool
        assert cluster["tool_distribution"][0]["error_rate_pct"] == pytest.approx(8.3, abs=0.1)
        # Routing entropy is between 0 and 1; this is skewed so should be low.
        assert 0.0 < cluster["routing_entropy"] < 0.7

    def test_sorts_clusters_by_call_count(self) -> None:
        records = [
            IntentRecord(intent_text="rare intent", frequency=1, tool_counts={"tool_a": 1}),
            IntentRecord(intent_text="popular intent", frequency=100, tool_counts={"tool_b": 100}),
        ]
        labels = np.array([0, 1], dtype=np.int64)
        embeddings = np.array([_unit([1.0, 0.0]), _unit([0.0, 1.0])], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings)

        assert snapshot["clusters"][0]["label"] == "popular intent"
        assert snapshot["clusters"][1]["label"] == "rare intent"

    def test_sample_intents_capped_and_sorted_by_frequency(self) -> None:
        records = [
            IntentRecord(intent_text=f"intent_{i}", frequency=10 - i, tool_counts={"tool_a": 10 - i}) for i in range(5)
        ]
        labels = np.array([0] * 5, dtype=np.int64)
        embeddings = np.array([_unit([1.0, 0.0])] * 5, dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings)

        cluster = snapshot["clusters"][0]
        assert cluster["sample_intents"] == ["intent_0", "intent_1", "intent_2"]

    def test_medoid_is_used_as_cluster_label(self) -> None:
        records = [
            IntentRecord(intent_text="edge_a", frequency=1, tool_counts={"tool_a": 1}),
            IntentRecord(intent_text="center", frequency=1, tool_counts={"tool_a": 1}),
            IntentRecord(intent_text="edge_b", frequency=1, tool_counts={"tool_a": 1}),
        ]
        labels = np.array([0, 0, 0], dtype=np.int64)
        embeddings = np.array(
            [
                _unit([1.0, 0.0]),
                _unit([0.5, 0.5]),
                _unit([0.0, 1.0]),
            ],
            dtype=np.float32,
        )

        snapshot = build_snapshot(records, labels, embeddings, distance_threshold=DEFAULT_DISTANCE_THRESHOLD)

        assert snapshot["clusters"][0]["label"] == "center"

    def test_misaligned_inputs_raise(self) -> None:
        records = [IntentRecord(intent_text="a", frequency=1, tool_counts={"tool_a": 1})]
        with pytest.raises(AssertionError):
            build_snapshot(records, np.array([0, 0], dtype=np.int64), np.array([_unit([1.0, 0.0])]))


# fetch_intent_corpus -----------------------------------------------------


class TestFetchIntentCorpus(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, BaseTest):
    """End-to-end: posthog_mcp_session in Postgres + mcp_tool_call in ClickHouse."""

    def _seed_session(
        self,
        session_id: str,
        intent: str,
        *,
        session_end_offset: timedelta = timedelta(minutes=-55),
    ) -> None:
        end = datetime.now(tz=UTC) + session_end_offset
        start = end - timedelta(minutes=5)
        MCPSession.objects.create(
            team=self.team,
            session_id=session_id,
            session_start=start,
            session_end=end,
            duration_seconds=300,
            intent=intent,
        )

    def _seed_tool_call(self, session_id: str, tool_name: str, is_error: bool = False) -> None:
        _create_event(
            event_uuid=uuid.uuid4(),
            event="mcp_tool_call",
            team=self.team,
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=1),
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": tool_name,
                "$mcp_is_error": is_error,
            },
        )

    def test_returns_empty_when_no_sessions(self) -> None:
        records, intent_by_session = fetch_intent_corpus(self.team)
        assert records == []
        assert intent_by_session == {}

    def test_aggregates_tool_calls_across_sessions_with_matching_intent(self) -> None:
        self._seed_session("session-a", "check feature flag rollout")
        self._seed_session("session-b", "check feature flag rollout")
        self._seed_tool_call("session-a", "feature_flag_get")
        self._seed_tool_call("session-a", "feature_flag_get")
        self._seed_tool_call("session-b", "feature_flag_get", is_error=True)
        self._seed_tool_call("session-b", "query_run")
        flush_persons_and_events()

        records, intent_by_session = fetch_intent_corpus(self.team)

        assert len(records) == 1
        assert records[0].intent_text == "check feature flag rollout"
        assert records[0].tool_counts == {"feature_flag_get": 3, "query_run": 1}
        assert records[0].error_counts == {"feature_flag_get": 1}
        assert records[0].frequency == 4
        assert intent_by_session == {
            "session-a": "check feature flag rollout",
            "session-b": "check feature flag rollout",
        }

    def test_keeps_intents_without_tool_calls_as_zero_call_records(self) -> None:
        # A session was logged but no events flowed through yet — we should
        # still surface the intent so the UI can show "no calls yet".
        self._seed_session("session-quiet", "quiet intent with no events")

        records, _ = fetch_intent_corpus(self.team)

        assert len(records) == 1
        assert records[0].intent_text == "quiet intent with no events"
        assert records[0].tool_counts == {}
        assert records[0].frequency == 1

    def test_lookback_days_excludes_sessions_outside_the_window(self) -> None:
        # In-window session (ends ~55 min ago).
        self._seed_session("recent", "recent intent")
        # Out-of-window session (ends 10 days ago, beyond the 7-day default).
        self._seed_session("old", "old intent", session_end_offset=timedelta(days=-10))

        records, intent_by_session = fetch_intent_corpus(self.team)

        assert {r.intent_text for r in records} == {"recent intent"}
        assert intent_by_session == {"recent": "recent intent"}

    @parameterized.expand(
        [
            ("default_7_excludes_old", 7, []),
            ("override_30_includes_old", 30, ["old intent"]),
        ]
    )
    def test_lookback_days_argument_is_respected(
        self, _name: str, lookback_days: int, expected_intents: list[str]
    ) -> None:
        # Session ends 10 days ago: excluded at 7 days, included at 30.
        self._seed_session("old", "old intent", session_end_offset=timedelta(days=-10))

        records, _ = fetch_intent_corpus(self.team, lookback_days=lookback_days)

        assert [r.intent_text for r in records] == expected_intents

    @parameterized.expand(
        [
            ("raw", NO_INTENT_RECORDED_FALLBACK),
            ("padded_whitespace", f"  {NO_INTENT_RECORDED_FALLBACK}  "),
        ]
    )
    def test_summariser_fallback_intent_is_excluded(self, _name: str, placeholder_text: str) -> None:
        # Session whose intent column holds the summariser's "nothing here"
        # placeholder — must be excluded so it doesn't form its own cluster.
        # Whitespace variants must also be excluded after .strip().
        self._seed_session("placeholder", placeholder_text)
        self._seed_session("real", "look up feature flag rollout")

        records, intent_by_session = fetch_intent_corpus(self.team)

        assert [r.intent_text for r in records] == ["look up feature flag rollout"]
        assert intent_by_session == {"real": "look up feature flag rollout"}
