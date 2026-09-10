"""Tests for the pure functions in intent_clustering.

These tests are intentionally light on Django/ClickHouse and heavy on the
algorithm. They cover the math (clustering, entropy, medoid) and the snapshot
shape we promise the frontend.
"""

import math
import uuid
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

import numpy as np
from parameterized import parameterized

from posthog.hogql.constants import DEFAULT_RETURNED_ROWS

from posthog.api.embedding_worker import EmbeddingResponse

from products.mcp_analytics.backend import intent_clustering
from products.mcp_analytics.backend.constants import MAX_SNAPSHOT_CLUSTERS
from products.mcp_analytics.backend.intent_clustering import (
    DEFAULT_DISTANCE_THRESHOLD,
    DESCRIPTION_EMBEDDING_PREFIX,
    EMBEDDING_MODEL,
    JOURNEY_DEPTH,
    MAX_ADVERTISED_LIST_EVENTS_PER_SESSION,
    MAX_ADVERTISED_TOOLS_PER_SESSION,
    MAX_DESCRIPTION_LENGTH,
    MAX_INTENT_TEXT_LENGTH,
    MAX_TOOL_NAME_LENGTH,
    MAX_TOOLS_IN_SNAPSHOT,
    MAX_TOOLS_PER_ADVERTISED_LIST,
    MIN_ADVERTISED_SESSIONS,
    NO_INTENT_RECORDED_FALLBACK,
    SNAPSHOT_VERSION,
    CallRecord,
    CorpusStats,
    IntentRecord,
    WindowStats,
    _content_hash,
    _decode_embedding,
    _encode_embedding,
    _medoid_index,
    _routing_entropy,
    build_call_corpus,
    build_snapshot,
    cluster_embeddings,
    compute_cluster_flows,
    compute_description_fit,
    compute_tool_overlaps,
    compute_tool_pivot,
    embed_texts_async,
    fetch_advertised_tools,
    fetch_session_calls,
    fetch_tool_descriptions,
    fetch_window_stats,
    sample_corpus_sessions,
    top_corpus_tools,
)
from products.mcp_analytics.backend.models import MCPIntentEmbeddingCache
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

# Helpers


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def _snapshot_record(intent: str, tool: str, count: int) -> IntentRecord:
    return IntentRecord(intent_text=intent, frequency=count, tool_counts={tool: count})


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

    def test_meta_marks_snapshot_as_sampled_not_population(self) -> None:
        # The page presents per-tool numbers as if they were the population; the
        # snapshot must carry the sampling/balance metadata so the UI can warn.
        records = [_snapshot_record("i1", "exec", 3), _snapshot_record("i2", "query-apm-spans", 1)]
        labels = np.array([0, 1], dtype=np.int64)
        embeddings = np.array([_unit([1.0, 0.0]), _unit([0.0, 1.0])], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings, calls_by_session={})

        meta = snapshot["computed_with"]
        assert meta["sampled"] is True
        assert "corpus_strategy" in meta
        assert "sampling_warning" in meta

    def test_misaligned_inputs_raise(self) -> None:
        records = [IntentRecord(intent_text="a", frequency=1, tool_counts={"tool_a": 1})]
        with pytest.raises(AssertionError):
            build_snapshot(records, np.array([0, 0], dtype=np.int64), np.array([_unit([1.0, 0.0])]))

    def test_caps_stored_clusters_and_keeps_the_full_count_in_meta(self) -> None:
        # A degenerate run (tight threshold, diverse corpus) can label almost every
        # intent as its own cluster; without the cap the persisted blob and the
        # unpaginated API response grow unbounded.
        n_total = MAX_SNAPSHOT_CLUSTERS + 5
        records = [
            IntentRecord(intent_text=f"intent_{i}", frequency=i + 1, tool_counts={"tool_a": i + 1})
            for i in range(n_total)
        ]
        labels = np.arange(n_total, dtype=np.int64)
        embeddings = np.array([_unit([1.0, float(i + 1)]) for i in range(n_total)], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings)

        assert len(snapshot["clusters"]) == MAX_SNAPSHOT_CLUSTERS
        assert snapshot["computed_with"]["n_clusters"] == n_total
        # The highest-volume clusters are the ones kept (call counts 1..n_total; the 5 smallest drop).
        assert min(cluster["call_count"] for cluster in snapshot["clusters"]) == 6

    def test_pivot_totals_survive_the_cluster_cap(self) -> None:
        # The cluster cap runs before the pivot, so without care every per-tool
        # total silently loses the calls of the clusters it dropped.
        n_total = MAX_SNAPSHOT_CLUSTERS + 5
        records = [
            IntentRecord(intent_text=f"intent_{i}", frequency=i + 1, tool_counts={"tool_a": i + 1})
            for i in range(n_total)
        ]
        labels = np.arange(n_total, dtype=np.int64)
        embeddings = np.array([_unit([1.0, float(i + 1)]) for i in range(n_total)], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings, calls_by_session={})

        tool = snapshot["tools"][0]
        assert tool["call_count"] == sum(range(1, n_total + 1))
        assert tool["n_clusters_served"] == n_total
        assert {entry["cluster_id"] for entry in tool["clusters"]} <= {c["id"] for c in snapshot["clusters"]}

    def test_pivot_tools_match_the_population_descriptions_are_fetched_for(self) -> None:
        # Descriptions are only fetched for top_corpus_tools(records). If the pivot
        # ranks a different population, a tool that made the pivot never has a
        # description fetched and renders as "none captured" for no visible reason.
        n_tools = MAX_TOOLS_IN_SNAPSHOT + 5
        records = [
            IntentRecord(intent_text=f"intent_{i}", frequency=i + 1, tool_counts={f"tool_{i:04d}": i + 1})
            for i in range(n_tools)
        ]
        labels = np.arange(n_tools, dtype=np.int64)
        embeddings = np.array([_unit([1.0, float(i + 1)]) for i in range(n_tools)], dtype=np.float32)

        snapshot = build_snapshot(records, labels, embeddings, calls_by_session={})

        assert {tool["tool"] for tool in snapshot["tools"]} == top_corpus_tools(records)

    def test_empty_corpus_keeps_the_coverage_it_does_know(self) -> None:
        # A run that saw traffic but could attribute none of it must not look
        # identical to a run that saw nothing at all — "0% of calls carried an
        # intent" is the message that tells the owner what to fix.
        snapshot = build_snapshot(
            [],
            np.array([], dtype=np.int64),
            np.zeros((0, 4), dtype=np.float32),
            window_stats=WindowStats(total_calls=400, calls_with_intent=0, sessions=25),
        )

        assert snapshot["clusters"] == []
        assert snapshot["computed_with"]["window_sessions"] == 25
        assert snapshot["computed_with"]["intent_coverage_pct"] == pytest.approx(0.0)

    def test_snapshot_is_versioned_and_v1_style_invocation_degrades(self) -> None:
        records = [IntentRecord(intent_text="a", frequency=1, tool_counts={"tool_a": 1})]
        snapshot = build_snapshot(records, np.array([0], dtype=np.int64), np.array([_unit([1.0, 0.0])]))

        assert snapshot["version"] == SNAPSHOT_VERSION
        assert snapshot["tools"] == []
        assert snapshot["tool_overlaps"] == []
        assert snapshot["clusters"][0]["switches"] == []
        assert snapshot["clusters"][0]["self_retries"] == []
        assert snapshot["computed_with"]["sampled_sessions"] is None
        assert snapshot["computed_with"]["intent_coverage_pct"] is None

    def test_full_v2_snapshot_carries_pivot_overlaps_and_meta(self) -> None:
        records = [
            IntentRecord(intent_text="check flags", frequency=3, session_count=1, tool_counts={"flag_get": 3}),
            IntentRecord(
                intent_text="run a query",
                frequency=3,
                session_count=1,
                tool_counts={"sql_run": 2, "flag_get": 1},
                error_counts={"sql_run": 1},
            ),
        ]
        labels = np.array([0, 1], dtype=np.int64)
        embeddings = np.array([_unit([1.0, 0.0]), _unit([0.0, 1.0])], dtype=np.float32)
        calls_by_session = {
            "s1": [
                CallRecord(session_id="s1", tool="flag_get", intent_text="check flags", is_error=False),
                CallRecord(session_id="s1", tool="flag_get", intent_text="check flags", is_error=False),
                CallRecord(session_id="s1", tool="flag_get", intent_text="check flags", is_error=False),
                CallRecord(session_id="s1", tool="sql_run", intent_text="run a query", is_error=True),
                CallRecord(session_id="s1", tool="sql_run", intent_text="run a query", is_error=False),
                CallRecord(session_id="s1", tool="flag_get", intent_text="run a query", is_error=False),
            ],
        }
        snapshot = build_snapshot(
            records,
            labels,
            embeddings,
            calls_by_session=calls_by_session,
            advertised_by_session={"s1": {"flag_get", "sql_run"}},
            tool_descriptions={"flag_get": "Reads a feature flag"},
            description_embeddings={"flag_get": _unit([1.0, 0.0])},
            corpus_stats=CorpusStats(total_calls=8, attributed_calls=6, imputed_calls=1, kept_calls=6),
            window_stats=WindowStats(total_calls=100, calls_with_intent=90, sessions=50),
        )

        assert snapshot["version"] == SNAPSHOT_VERSION
        tools = {t["tool"]: t for t in snapshot["tools"]}
        assert set(tools) == {"flag_get", "sql_run"}
        assert tools["flag_get"]["call_count"] == 4
        assert tools["flag_get"]["description"] == "Reads a feature flag"
        assert tools["sql_run"]["description"] is None
        assert len(snapshot["tool_overlaps"]) == 1

        meta = snapshot["computed_with"]
        assert meta["corpus"] == "per_call"
        assert meta["sampled_sessions"] == 1
        assert meta["window_sessions"] == 50
        assert meta["session_coverage_pct"] == pytest.approx(2.0)
        assert meta["intent_coverage_pct"] == pytest.approx(90.0)
        assert meta["imputed_call_pct"] == pytest.approx(100.0 * 1 / 6, abs=0.1)
        assert meta["unattributed_call_pct"] == pytest.approx(25.0)
        assert meta["corpus_call_coverage_pct"] == pytest.approx(100.0)
        assert meta["advertisement_coverage_pct"] == pytest.approx(100.0)
        assert meta["n_tools"] == 2
        assert meta["description_coverage_pct"] == pytest.approx(50.0)


# build_call_corpus --------------------------------------------------------


class TestBuildCallCorpus:
    def test_attributes_tool_counts_to_the_calls_own_intent(self) -> None:
        # The v1 pipeline smeared the session's first intent across every call in
        # the session, so tools used for a later intent were mis-credited.
        rows = [
            ("s1", "flag_get", "check flags", False),
            ("s1", "sql_run", "run a query", False),
        ]

        records, _, _ = build_call_corpus(rows)

        by_text = {r.intent_text: r for r in records}
        assert by_text["check flags"].tool_counts == {"flag_get": 1}
        assert by_text["run a query"].tool_counts == {"sql_run": 1}

    def test_locf_carries_intent_within_but_not_across_sessions(self) -> None:
        rows = [
            ("s1", "flag_get", "check flags", False),
            ("s1", "sql_run", "", False),
            ("s2", "insight_get", "", False),
            ("s2", "sql_run", "run a query", False),
        ]

        records, calls_by_session, stats = build_call_corpus(rows)

        by_text = {r.intent_text: r for r in records}
        assert by_text["check flags"].tool_counts == {"flag_get": 1, "sql_run": 1}
        assert by_text["run a query"].tool_counts == {"sql_run": 1}
        assert [c.intent_text for c in calls_by_session["s2"]] == [None, "run a query"]
        assert stats.total_calls == 4
        assert stats.attributed_calls == 3
        assert stats.imputed_calls == 1

    def test_error_counts_and_distinct_session_count(self) -> None:
        rows = [
            ("s1", "flag_get", "check flags", True),
            ("s2", "flag_get", "check flags", False),
            ("s2", "flag_get", "check flags", True),
        ]

        records, _, _ = build_call_corpus(rows)

        assert len(records) == 1
        assert records[0].frequency == 3
        assert records[0].session_count == 2
        assert records[0].error_counts == {"flag_get": 2}

    @parameterized.expand(
        [
            ("placeholder", NO_INTENT_RECORDED_FALLBACK),
            ("padded_placeholder", f"  {NO_INTENT_RECORDED_FALLBACK}  "),
            ("empty", ""),
            ("whitespace", "   "),
        ]
    )
    def test_non_intents_are_treated_as_absent(self, _name: str, raw_intent: str) -> None:
        records, calls_by_session, stats = build_call_corpus([("s1", "flag_get", raw_intent, False)])

        assert records == []
        assert calls_by_session["s1"][0].intent_text is None
        assert stats.attributed_calls == 0

    def test_oversized_intent_is_clipped_before_grouping(self) -> None:
        records, _, _ = build_call_corpus([("s1", "flag_get", "x" * (MAX_INTENT_TEXT_LENGTH * 3), False)])

        assert [len(r.intent_text) for r in records] == [MAX_INTENT_TEXT_LENGTH]

    def test_top_n_keeps_highest_call_count_intents_and_reports_kept_calls(self) -> None:
        rows = [("s1", "t", "popular", False)] * 3 + [("s2", "t", "middling", False)] * 2 + [("s3", "t", "rare", False)]

        records, _, stats = build_call_corpus(rows, top_n=2)

        assert [r.intent_text for r in records] == ["popular", "middling"]
        assert stats.attributed_calls == 6
        assert stats.kept_calls == 5


# stratified corpus ---------------------------------------------------------


class TestStratifySessionIds:
    """The uniform 0.5% session sample is what erases low/mid-volume tools (the
    APM logs/tracing/metrics complaint). Stratifying the *session ids* before
    the corpus SQL guarantees every tool keeps a floor of sessions, so no tool
    is silently dropped from clustering just because exec/scout dominate."""

    def test_every_tool_keeps_a_floor_of_sessions(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions: dict[str, set[str]] = {
            "exec": {f"exec-s{i}" for i in range(2000)},
            "query-apm-spans": {f"apm-s{i}" for i in range(30)},
        }
        union = set().union(*tool_sessions.values())

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=400, max_total_sessions=2000)

        # The 30-session APM tool must survive even though a uniform sample of
        # ~2000/2030 will statistically drop most of them.
        assert {sid for sid in selected if sid.startswith("apm-s")} == set(tool_sessions["query-apm-spans"])
        assert selected.issubset(union)

    def test_total_respects_max_total_sessions(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions = {f"tool_{t}": {f"tool_{t}-s{i}" for i in range(600)} for t in range(10)}

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=400, max_total_sessions=2000)

        assert len(selected) <= 2000

    def test_selection_is_deterministic(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions = {f"tool_{t}": {f"tool_{t}-s{i}" for i in range(50)} for t in range(5)}

        first = stratify_session_ids(tool_sessions, min_sessions_per_tool=20, max_total_sessions=80)
        second = stratify_session_ids(tool_sessions, min_sessions_per_tool=20, max_total_sessions=80)

        assert first == second

    def test_scarce_tool_is_kept_entirely(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions = {"query-metrics": {f"m-s{i}" for i in range(4)}, "exec": {f"e-s{i}" for i in range(3000)}}

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=400, max_total_sessions=2000)

        assert {sid for sid in selected if sid.startswith("m-s")} == tool_sessions["query-metrics"]

    def test_budget_apportions_floors_and_stays_within_total(self) -> None:
        # Regression for the over-budget trimming bug: 3 x 250 = 750 must come
        # back under a 700 budget, and no tool may be skipped.
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions = {f"tool_{t}": {f"tool_{t}-s{i}" for i in range(300)} for t in range(3)}

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=250, max_total_sessions=700)

        assert len(selected) <= 700
        for t in range(3):
            assert any(sid.startswith(f"tool_{t}-s") for sid in selected), f"tool_{t} was skipped"

    def test_late_tool_is_not_skipped_when_floors_fill_the_budget(self) -> None:
        # Regression for the break that skipped every tool once earlier floors
        # hit the budget: a late, higher-volume tool must still get a floor.
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        tool_sessions: dict[str, set[str]] = {
            "alpha": {f"a-s{i}" for i in range(500)},
            "beta": {f"b-s{i}" for i in range(500)},
            "zeta": {f"z-s{i}" for i in range(1000)},
        }

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=400, max_total_sessions=900)

        assert any(sid.startswith("z-s") for sid in selected)
        assert len(selected) <= 900

    def test_never_exceeds_budget_when_many_tools_share_many_sessions(self) -> None:
        # 10 tools each with 400 shared sessions: sum of floors (4000) far
        # exceeds the budget even after de-dup (shared ids), so any overshoot
        # must be trimmed.
        from products.mcp_analytics.backend.intent_clustering import stratify_session_ids

        shared = {f"s{i}" for i in range(400)}
        tool_sessions = {f"tool_{t}": set(shared) for t in range(10)}

        selected = stratify_session_ids(tool_sessions, min_sessions_per_tool=400, max_total_sessions=1500)

        assert len(selected) <= 1500


class TestSelectCorpusSessions:
    """The per-tool buckets only carry each tool's floor, so the rest of the
    corpus budget is filled from the uniform hash sample. The top-up must never
    displace a floor session — that would undo the stratification — and must
    still produce a full-size corpus for a team with only a couple of tools."""

    def test_floors_survive_a_uniform_sample_larger_than_the_budget(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import select_corpus_sessions

        tool_sessions = {"query-metrics": {"m-s0", "m-s1"}}
        uniform = [f"exec-s{i}" for i in range(50)]

        selected = select_corpus_sessions(tool_sessions, uniform, min_sessions_per_tool=400, max_total_sessions=10)

        assert {"m-s0", "m-s1"}.issubset(selected)
        assert len(selected) == 10

    def test_uniform_sample_is_the_whole_corpus_when_buckets_are_unavailable(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import select_corpus_sessions

        uniform = [f"exec-s{i}" for i in range(30)]

        selected = select_corpus_sessions({}, uniform, min_sessions_per_tool=400, max_total_sessions=10)

        assert len(selected) == 10
        assert set(selected).issubset(uniform)

    def test_budget_already_filled_by_floors_admits_no_top_up(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import select_corpus_sessions

        tool_sessions = {f"tool_{t}": {f"tool_{t}-s{i}" for i in range(3)} for t in range(4)}

        selected = select_corpus_sessions(tool_sessions, ["uniform-s0"], min_sessions_per_tool=3, max_total_sessions=12)

        assert "uniform-s0" not in selected
        assert len(selected) == 12


class TestCapPerToolCallVolume:
    """After sampling, a single high-volume tool (exec) must not be allowed to
    occupy the whole intent corpus; cap its attributed calls so mid/low tools
    retain enough signal to cluster."""

    def test_caps_overrepresented_tool_and_reports_it(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import cap_per_tool_call_volume

        rows = [("s1", "exec", "operate", False)] * 100 + [("s2", "query-logs", "tail logs", False)] * 2

        result = cap_per_tool_call_volume(rows, max_calls_per_tool=10)

        per_tool_count: dict[str, int] = {}
        for _, tool, _, _ in result.kept_rows:
            per_tool_count[tool] = per_tool_count.get(tool, 0) + 1
        assert per_tool_count["exec"] <= 10
        # low-volume tool is untouched
        assert per_tool_count["query-logs"] == 2
        assert result.per_tool_report["exec"]["dropped"] >= 90

    def test_deterministic_about_which_calls_survive(self) -> None:
        from products.mcp_analytics.backend.intent_clustering import cap_per_tool_call_volume

        rows = [("s1", "exec", f"op {i}", False) for i in range(50)]

        first = cap_per_tool_call_volume(rows, max_calls_per_tool=10)
        second = cap_per_tool_call_volume(rows, max_calls_per_tool=10)

        assert first == second


# compute_cluster_flows ----------------------------------------------------


def _record(intent: str) -> IntentRecord:
    return IntentRecord(intent_text=intent, frequency=1, tool_counts={})


class TestComputeClusterFlows:
    def test_journeys_use_only_the_clusters_own_calls(self) -> None:
        # One session serving two intents: each cluster's journey and outcome must
        # come from its own calls, not the whole session (an error on the other
        # intent's call must not mark this cluster's journey as errored).
        records = [_record("intent a"), _record("intent b")]
        labels = np.array([0, 1], dtype=np.int64)
        calls_by_session = {
            "s1": [
                CallRecord(session_id="s1", tool="tool_x", intent_text="intent a", is_error=False),
                CallRecord(session_id="s1", tool="tool_z", intent_text="intent b", is_error=True),
                CallRecord(session_id="s1", tool="tool_y", intent_text="intent a", is_error=False),
            ],
        }

        flows = compute_cluster_flows(records, labels, calls_by_session)

        journey_a = flows[0]["journey"]
        assert journey_a["paths"] == [{"steps": ["tool_x", "tool_y", None, None], "outcome": "completed", "count": 1}]
        journey_b = flows[1]["journey"]
        assert journey_b["paths"][0]["outcome"] == "error"
        assert flows[0]["session_ids"] == {"s1"}

    def test_journey_clips_to_depth(self) -> None:
        records = [_record("intent a")]
        labels = np.array([0], dtype=np.int64)
        calls = [
            CallRecord(session_id="s1", tool=f"tool_{i}", intent_text="intent a", is_error=False)
            for i in range(JOURNEY_DEPTH + 2)
        ]

        flows = compute_cluster_flows(records, labels, {"s1": calls})

        steps = flows[0]["journey"]["paths"][0]["steps"]
        assert len(steps) == JOURNEY_DEPTH
        assert steps == [f"tool_{i}" for i in range(JOURNEY_DEPTH)]

    @parameterized.expand(
        [
            (
                "error_then_other_tool_is_a_switch",
                True,
                "tool_b",
                [{"from_tool": "tool_a", "to_tool": "tool_b", "count": 1}],
                [],
            ),
            ("error_then_same_tool_is_a_retry", True, "tool_a", [], [{"tool": "tool_a", "count": 1}]),
            ("success_then_other_tool_is_neither", False, "tool_b", [], []),
        ]
    )
    def test_switch_and_retry_extraction(
        self,
        _name: str,
        first_errors: bool,
        second_tool: str,
        expected_switches: list[dict],
        expected_retries: list[dict],
    ) -> None:
        records = [_record("intent a")]
        labels = np.array([0], dtype=np.int64)
        calls_by_session = {
            "s1": [
                CallRecord(session_id="s1", tool="tool_a", intent_text="intent a", is_error=first_errors),
                CallRecord(session_id="s1", tool=second_tool, intent_text="intent a", is_error=False),
            ],
        }

        flows = compute_cluster_flows(records, labels, calls_by_session)

        assert flows[0]["switches"] == expected_switches
        assert flows[0]["self_retries"] == expected_retries

    def test_unattributed_calls_are_invisible_to_flows(self) -> None:
        records = [_record("intent a")]
        labels = np.array([0], dtype=np.int64)
        calls_by_session = {
            "s1": [
                CallRecord(session_id="s1", tool="tool_a", intent_text="intent a", is_error=True),
                CallRecord(session_id="s1", tool="stray", intent_text=None, is_error=False),
                CallRecord(session_id="s1", tool="tool_b", intent_text="intent a", is_error=False),
            ],
        }

        flows = compute_cluster_flows(records, labels, calls_by_session)

        assert flows[0]["journey"]["paths"][0]["steps"] == ["tool_a", "tool_b", None, None]
        assert flows[0]["switches"] == [{"from_tool": "tool_a", "to_tool": "tool_b", "count": 1}]


# top_corpus_tools ----------------------------------------------------------


class TestTopCorpusTools:
    def test_caps_to_the_highest_volume_corpus_tools(self) -> None:
        # A caller emitting unique tool names per call could otherwise turn one
        # recompute into one embedding request per unique name.
        records = [
            IntentRecord(intent_text="a", frequency=5, tool_counts={"busy": 5}),
            IntentRecord(intent_text="b", frequency=3, tool_counts={"quiet": 1, "busy": 2}),
        ]

        assert top_corpus_tools(records, max_tools=1) == {"busy"}


# compute_description_fit --------------------------------------------------


class TestComputeDescriptionFit:
    def test_fit_is_cosine_to_cluster_centroid(self) -> None:
        embeddings = np.array([_unit([1.0, 0.0]), _unit([1.0, 0.0]), _unit([0.0, 1.0])], dtype=np.float32)
        labels = np.array([0, 0, 1], dtype=np.int64)

        fit = compute_description_fit(embeddings, labels, {"tool_a": _unit([1.0, 0.0])})

        assert fit["tool_a"][0] == pytest.approx(1.0)
        assert fit["tool_a"][1] == pytest.approx(0.0, abs=1e-6)

    def test_tools_without_embeddings_are_absent(self) -> None:
        embeddings = np.array([_unit([1.0, 0.0])], dtype=np.float32)
        labels = np.array([0], dtype=np.int64)

        assert compute_description_fit(embeddings, labels, {}) == {}


# compute_tool_pivot -------------------------------------------------------


def _cluster_fixture() -> list[dict[str, Any]]:
    return [
        {
            "id": 0,
            "label": "check flags",
            "call_count": 10,
            "routing_entropy": 0.5,
            "tool_distribution": [
                {"tool": "t1", "count": 6, "pct": 60.0, "errors": 1, "error_rate_pct": 16.7},
                {"tool": "t2", "count": 4, "pct": 40.0, "errors": 0, "error_rate_pct": 0.0},
            ],
        },
        {
            "id": 1,
            "label": "run queries",
            "call_count": 4,
            "routing_entropy": 0.0,
            "tool_distribution": [
                {"tool": "t1", "count": 4, "pct": 100.0, "errors": 0, "error_rate_pct": 0.0},
            ],
        },
    ]


def _attributed_call(session: str, tool: str, intent: str = "check flags") -> CallRecord:
    return CallRecord(session_id=session, tool=tool, intent_text=intent, is_error=False)


class TestComputeToolPivot:
    def test_capture_rank_competitor_and_contested_score(self) -> None:
        pivot, dropped = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session={"s1": [_attributed_call("s1", "t1"), _attributed_call("s1", "t2")]},
            advertised_by_session={},
            tool_descriptions={},
            description_fit={},
        )

        assert dropped == 0
        by_tool = {t["tool"]: t for t in pivot}
        t1 = by_tool["t1"]
        assert t1["call_count"] == 10
        assert t1["error_count"] == 1
        # Call-weighted mean of cluster entropies: (6*0.5 + 4*0.0) / 10.
        assert t1["contested_score"] == pytest.approx(0.3)
        assert [c["cluster_id"] for c in t1["clusters"]] == [0, 1]
        first = t1["clusters"][0]
        assert first["capture_pct"] == pytest.approx(60.0)
        assert first["rank"] == 1
        assert first["top_competitor"] == {"tool": "t2", "pct": 40.0}
        t2 = by_tool["t2"]
        assert t2["clusters"][0]["rank"] == 2
        assert t2["clusters"][0]["top_competitor"] == {"tool": "t1", "pct": 60.0}
        assert by_tool["t1"]["clusters"][1]["top_competitor"] is None

    def test_advertised_denominator_ignores_sessions_absent_from_the_corpus(self) -> None:
        # The row cap can drop whole sessions after their ids were sampled. Leaving
        # them in the advertised denominator with nothing in the numerator drags
        # every discovery rate down exactly when the truncation warning fires.
        advertised = {f"s{i}": {"t1"} for i in range(MIN_ADVERTISED_SESSIONS + 3)}
        calls = {f"s{i}": [_attributed_call(f"s{i}", "t1")] for i in range(MIN_ADVERTISED_SESSIONS)}

        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session=calls,
            advertised_by_session=advertised,
            tool_descriptions={},
            description_fit={},
        )

        t1 = {t["tool"]: t for t in pivot}["t1"]
        assert t1["advertised_sessions"] == MIN_ADVERTISED_SESSIONS
        assert t1["discovery_rate_pct"] == pytest.approx(100.0)

    def test_discovery_rate_needs_the_advertised_floor(self) -> None:
        # t1 advertised in 5 corpus sessions and called in 3 of them: measurable at
        # exactly the floor. t2 advertised in only 1 session: below the floor, so
        # null. The other two sessions are in the corpus for a different tool.
        advertised = {f"s{i}": {"t1"} for i in range(MIN_ADVERTISED_SESSIONS)}
        advertised["s0"] = {"t1", "t2"}
        calls = {f"s{i}": [_attributed_call(f"s{i}", "t1")] for i in range(3)}
        calls |= {f"s{i}": [_attributed_call(f"s{i}", "t2")] for i in (3, 4)}

        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session=calls,
            advertised_by_session=advertised,
            tool_descriptions={},
            description_fit={},
        )

        by_tool = {t["tool"]: t for t in pivot}
        assert by_tool["t1"]["advertised_sessions"] == 5
        assert by_tool["t1"]["called_when_advertised"] == 3
        assert by_tool["t1"]["discovery_rate_pct"] == pytest.approx(60.0)
        assert by_tool["t2"]["advertised_sessions"] == 1
        assert by_tool["t2"]["discovery_rate_pct"] is None

    def test_description_and_fit_are_attached(self) -> None:
        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session={},
            advertised_by_session={},
            tool_descriptions={"t1": "Reads a flag"},
            description_fit={"t1": {0: 0.42}},
        )

        by_tool = {t["tool"]: t for t in pivot}
        assert by_tool["t1"]["description"] == "Reads a flag"
        assert by_tool["t1"]["clusters"][0]["description_fit"] == pytest.approx(0.42)
        assert by_tool["t1"]["clusters"][1]["description_fit"] is None
        assert by_tool["t2"]["description"] is None

    def test_max_tools_cap_drops_lowest_volume_tools(self) -> None:
        pivot, dropped = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session={},
            advertised_by_session={},
            tool_descriptions={},
            description_fit={},
            max_tools=1,
        )

        assert [t["tool"] for t in pivot] == ["t1"]
        assert dropped == 1

    def test_entries_carry_no_per_cluster_constants(self) -> None:
        # label, cluster call count, and entropy are constants of the cluster, and
        # a tool x cluster entry repeats them once per tool. At the caps this file
        # sets that is megabytes of duplicated intent text in one JSONB blob, which
        # is exactly what the cluster cap exists to prevent. The client joins the
        # cluster's own fields on cluster_id instead.
        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session={},
            advertised_by_session={},
            tool_descriptions={},
            description_fit={},
        )

        assert set(pivot[0]["clusters"][0]) == {
            "cluster_id",
            "calls",
            "capture_pct",
            "rank",
            "description_fit",
            "top_competitor",
        }

    def test_totals_span_every_cluster_while_entries_stay_joinable(self) -> None:
        # Clusters past the snapshot cap are dropped from the blob, but their calls
        # still happened: per-tool totals must count them, or the pivot silently
        # under-reports. Entries stay restricted to persisted clusters so every
        # cluster_id still resolves client-side.
        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session={},
            advertised_by_session={},
            tool_descriptions={},
            description_fit={},
            snapshot_cluster_ids={0},
        )

        t1 = {t["tool"]: t for t in pivot}["t1"]
        assert t1["call_count"] == 10
        assert t1["n_clusters_served"] == 2
        assert [entry["cluster_id"] for entry in t1["clusters"]] == [0]

    def test_session_count_counts_only_intent_attributed_calls(self) -> None:
        # call_count is attributed calls only, and compute_tool_overlaps builds its
        # session sets the same way. Counting unattributed calls here lets a tool
        # show a healthy discovery rate driven entirely by calls that never entered
        # a cluster.
        calls = {
            "s-attributed": [_attributed_call("s-attributed", "t1")],
            "s-unattributed": [CallRecord(session_id="s-unattributed", tool="t1", intent_text=None, is_error=False)],
        }

        pivot, _ = compute_tool_pivot(
            _cluster_fixture(),
            calls_by_session=calls,
            advertised_by_session={"s-attributed": {"t1"}, "s-unattributed": {"t1"}},
            tool_descriptions={},
            description_fit={},
        )

        t1 = {t["tool"]: t for t in pivot}["t1"]
        assert t1["session_count"] == 1
        assert t1["called_when_advertised"] == 1


# compute_tool_overlaps ----------------------------------------------------


class TestComputeToolOverlaps:
    def test_contested_calls_sum_min_across_clusters(self) -> None:
        calls_by_session = {
            "s1": [_attributed_call("s1", "t1"), _attributed_call("s1", "t2")],
            "s2": [_attributed_call("s2", "t1")],
        }

        overlaps, dropped = compute_tool_overlaps(_cluster_fixture(), calls_by_session)

        assert dropped == 0
        assert overlaps == [
            {
                "tool_a": "t1",
                "tool_b": "t2",
                "contested_calls": 4,
                "sessions_with_both": 1,
                "sessions_with_either": 2,
                "top_cluster_id": 0,
            }
        ]

    def test_max_pairs_cap_reports_dropped(self) -> None:
        overlaps, dropped = compute_tool_overlaps(_cluster_fixture(), {}, max_pairs=0)

        assert overlaps == []
        assert dropped == 1

    def test_pair_expansion_only_considers_each_clusters_head(self) -> None:
        # An event sender controls tool names, so one intent can carry thousands of
        # distinct tools; expanding all O(n^2) pairs before ranking would blow up
        # the recompute. Only the head of each distribution enters pair expansion.
        distribution: list[dict[str, Any]] = [
            {"tool": f"t{i}", "count": 100 - i, "pct": 1.0, "errors": 0, "error_rate_pct": 0.0} for i in range(4)
        ]
        clusters = [
            {
                "id": 0,
                "label": "x",
                "call_count": sum(entry["count"] for entry in distribution),
                "routing_entropy": 0.5,
                "tool_distribution": distribution,
            }
        ]

        overlaps, _ = compute_tool_overlaps(clusters, {}, max_tools_per_cluster=2)

        assert [(o["tool_a"], o["tool_b"]) for o in overlaps] == [("t0", "t1")]


# Corpus queries (ClickHouse-backed) ---------------------------------------


class TestCorpusQueries(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, BaseTest):
    """End-to-end coverage of the ClickHouse corpus queries behind the v2 pipeline."""

    def _seed_tool_call(
        self,
        session_id: str,
        tool_name: str,
        is_error: bool = False,
        intent: str | None = None,
        timestamp: datetime | None = None,
        exec_tool_name: str | None = None,
        description: str | None = None,
    ) -> None:
        properties: dict[str, Any] = {
            "$session_id": session_id,
            "$mcp_tool_name": tool_name,
            "$mcp_is_error": is_error,
        }
        if intent is not None:
            properties["$mcp_intent"] = intent
        if exec_tool_name is not None:
            properties["$mcp_exec_tool_call_name"] = exec_tool_name
        if description is not None:
            properties["$mcp_tool_description"] = description
        _create_event(
            event_uuid=uuid.uuid4(),
            event="$mcp_tool_call",
            team=self.team,
            distinct_id="seed",
            timestamp=timestamp or (datetime.now(tz=UTC) - timedelta(hours=1)),
            properties=properties,
        )

    def _seed_tools_list(self, session_id: str, tool_names: list[str]) -> None:
        _create_event(
            event_uuid=uuid.uuid4(),
            event="$mcp_tools_list",
            team=self.team,
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=1),
            properties={"$session_id": session_id, "$mcp_listed_tool_names": tool_names},
        )

    def test_sample_returns_only_sessions_that_recorded_an_intent(self) -> None:
        self._seed_tool_call("session-a", "execute_sql", intent="find slow queries")
        self._seed_tool_call("session-quiet", "execute_sql")
        # Sessionless intent events must not enter the corpus.
        self._seed_tool_call("", "execute_sql", intent="orphan intent")
        flush_persons_and_events()

        assert sample_corpus_sessions(self.team) == ["session-a"]

    @parameterized.expand(
        [
            ("default_7_excludes_old", 7, []),
            ("override_30_includes_old", 30, ["session-old"]),
        ]
    )
    def test_sample_respects_lookback_window(self, _name: str, lookback_days: int, expected: list[str]) -> None:
        self._seed_tool_call(
            "session-old",
            "execute_sql",
            intent="old event intent",
            timestamp=datetime.now(tz=UTC) - timedelta(days=10),
        )
        flush_persons_and_events()

        assert sample_corpus_sessions(self.team, lookback_days=lookback_days) == expected

    def test_session_calls_are_ordered_and_use_the_effective_tool_name(self) -> None:
        base = datetime.now(tz=UTC) - timedelta(hours=2)
        self._seed_tool_call(
            "session-a", "exec", intent="find slow queries", timestamp=base, exec_tool_name="execute_sql"
        )
        self._seed_tool_call("session-a", "query_trends", timestamp=base + timedelta(minutes=1), is_error=True)
        self._seed_tool_call("session-b", "feature_flag_get", intent="check flags")
        flush_persons_and_events()

        rows = fetch_session_calls(self.team, ["session-a", "session-b"])

        by_session: dict[str, list] = {}
        for row in rows:
            by_session.setdefault(row[0], []).append(row)
        assert [(r[1], r[2], r[3]) for r in by_session["session-a"]] == [
            ("execute_sql", "find slow queries", False),
            ("query_trends", "", True),
        ]
        assert [(r[1], r[2], r[3]) for r in by_session["session-b"]] == [("feature_flag_get", "check flags", False)]

    def test_oversized_sender_strings_are_clipped_at_the_sql_boundary(self) -> None:
        # A sender with the capture token controls these strings; without the SQL
        # clip a recompute materializes up to 50k full-size values in worker memory.
        long_tool = "t" * (MAX_TOOL_NAME_LENGTH + 50)
        long_intent = "i" * (MAX_INTENT_TEXT_LENGTH + 50)
        self._seed_tool_call("session-a", long_tool, intent=long_intent)
        self._seed_tools_list("session-a", [long_tool])
        flush_persons_and_events()

        rows = fetch_session_calls(self.team, ["session-a"])
        advertised = fetch_advertised_tools(self.team, ["session-a"])

        assert rows[0][1] == long_tool[:MAX_TOOL_NAME_LENGTH]
        assert rows[0][2] == long_intent[:MAX_INTENT_TEXT_LENGTH]
        # Discovery matching depends on the calls and advertised-catalog queries
        # clipping tool names identically.
        assert advertised["session-a"] == {rows[0][1]}

    def test_advertised_tools_union_across_tools_list_events(self) -> None:
        self._seed_tools_list("session-a", ["exec", "render-ui"])
        self._seed_tools_list("session-a", ["exec", "query_trends"])
        self._seed_tools_list("session-other", ["exec"])
        flush_persons_and_events()

        advertised = fetch_advertised_tools(self.team, ["session-a", "session-no-list"])

        assert advertised == {"session-a": {"exec", "render-ui", "query_trends"}}

    def test_advertised_catalog_is_bounded_per_list_and_per_session(self) -> None:
        # Both the array and the number of tools-list events are sender-controlled, and the
        # union aggregates both — without the SQL bounds one session can make the
        # advertised-catalog aggregation arbitrarily large in ClickHouse memory.
        oversized = [f"tool-{i}" for i in range(MAX_TOOLS_PER_ADVERTISED_LIST + 50)]
        self._seed_tools_list("session-wide", oversized)
        for i in range(MAX_ADVERTISED_LIST_EVENTS_PER_SESSION + 5):
            self._seed_tools_list("session-chatty", [f"chatty-{i}"])
        flush_persons_and_events()

        # A third session pushes the distinct union past the per-session bound with
        # events that each stay under the per-event and per-session-event caps.
        for i in range(3):
            self._seed_tools_list("session-union", [f"union-{i}-{j}" for j in range(400)])
        flush_persons_and_events()

        advertised = fetch_advertised_tools(self.team, ["session-wide", "session-chatty", "session-union"])

        assert len(advertised["session-wide"]) == MAX_TOOLS_PER_ADVERTISED_LIST
        assert len(advertised["session-chatty"]) <= MAX_ADVERTISED_LIST_EVENTS_PER_SESSION
        assert len(advertised["session-union"]) == MAX_ADVERTISED_TOOLS_PER_SESSION

    def test_tools_by_session_buckets_intent_bearing_sessions_by_effective_tool(self) -> None:
        # session-a carries an intent; session-quiet does not, so its tools must
        # not buckify it. The exec wrapper resolves to the inner effective tool.
        self._seed_tool_call("session-a", "query-logs", intent="tail error logs")
        self._seed_tool_call("session-a", "exec", intent="tail error logs", exec_tool_name="query-apm-spans")
        self._seed_tool_call("session-quiet", "query-metrics")
        flush_persons_and_events()

        buckets = intent_clustering.fetch_tools_by_session(self.team)

        assert buckets.get("query-logs") == {"session-a"}
        # the exec-wrapped call buckets under its inner tool
        assert buckets.get("query-apm-spans") == {"session-a"}
        assert "session-quiet" not in buckets.get("query-metrics", set())

    def test_tool_buckets_are_capped_per_tool_not_globally(self) -> None:
        # A global cap on candidate sessions re-erases the low-volume tool the
        # per-tool floor exists to protect: at high total volume its sessions
        # fall outside the hash-ordered cut before any bucketing happens, so the
        # floor has nothing left to keep. The cap has to apply per tool.
        for i in range(12):
            self._seed_tool_call(f"exec-s{i}", "exec", intent="operate the thing")
        for i in range(2):
            self._seed_tool_call(f"metrics-s{i}", "query-metrics", intent="check p99 latency")
        flush_persons_and_events()

        buckets = intent_clustering.fetch_tools_by_session(self.team, max_sessions_per_tool=3)

        assert buckets["query-metrics"] == {"metrics-s0", "metrics-s1"}
        # exec is capped at the same number, so the two buckets together hold
        # more sessions than the cap — the pool was never cut globally.
        assert len(buckets["exec"]) == 3

    def test_window_stats_count_calls_intents_and_sessions(self) -> None:
        self._seed_tool_call("session-a", "execute_sql", intent="find slow queries")
        self._seed_tool_call("session-a", "query_trends")
        self._seed_tool_call("session-b", "feature_flag_get")
        # The corpus query requires a tool name, so nameless calls must stay out of
        # these denominators too — intent_coverage_pct is read against the corpus.
        self._seed_tool_call("session-a", "")
        self._seed_tool_call("session-nameless", "")
        flush_persons_and_events()

        stats = fetch_window_stats(self.team)

        assert stats == WindowStats(total_calls=3, calls_with_intent=1, sessions=2)

    def test_tool_descriptions_take_the_latest_and_clip(self) -> None:
        base = datetime.now(tz=UTC) - timedelta(hours=3)
        self._seed_tool_call("s1", "execute_sql", description="old description", timestamp=base)
        self._seed_tool_call(
            "s1",
            "execute_sql",
            description="new " + "x" * MAX_DESCRIPTION_LENGTH,
            timestamp=base + timedelta(minutes=5),
        )
        self._seed_tool_call("s1", "query_trends", timestamp=base)
        flush_persons_and_events()

        descriptions = fetch_tool_descriptions(self.team, ["execute_sql"])

        # query_trends has calls in the window but is outside the requested set, so
        # it never enters the aggregation; execute_sql resolves to its newest text.
        assert set(descriptions) == {"execute_sql"}
        assert descriptions["execute_sql"].startswith("new ")
        assert len(descriptions["execute_sql"]) == MAX_DESCRIPTION_LENGTH
        assert fetch_tool_descriptions(self.team, []) == {}

    def test_corpus_queries_are_not_truncated_at_the_default_hogql_limit(self) -> None:
        # execute_hogql_query injects LIMIT 100 into any query without an explicit
        # LIMIT; every corpus query returns one-plus rows per sampled session, so a
        # corpus above 100 sessions would silently lose calls and advertisements.
        n_sessions = DEFAULT_RETURNED_ROWS + 20
        for i in range(n_sessions):
            self._seed_tool_call(f"session-{i}", "execute_sql", intent=f"unique intent {i}")
            self._seed_tools_list(f"session-{i}", ["execute_sql"])
        flush_persons_and_events()

        session_ids = sample_corpus_sessions(self.team)
        assert len(session_ids) == n_sessions

        rows = fetch_session_calls(self.team, session_ids)
        assert len(rows) == n_sessions

        advertised = fetch_advertised_tools(self.team, session_ids)
        assert len(advertised) == n_sessions


# Embedding helpers -----------------------------------------------------


class TestEmbeddingHelpers:
    def test_content_hash_includes_prefix(self) -> None:
        # The prefix is what we actually embed, so the hash must include it.
        assert _content_hash("hello") != _content_hash("ello")
        assert _content_hash("hello") == _content_hash("hello")  # stable

    def test_content_hash_separates_embedding_kinds(self) -> None:
        # Intent and description embeddings share one cache table; identical text
        # under different prefixes must never collide into one cache row.
        assert _content_hash("hello", prefix=DESCRIPTION_EMBEDDING_PREFIX) != _content_hash("hello")

    def test_encode_decode_round_trips_to_float32(self) -> None:
        vec = [0.1, -0.2, 0.5, 1.5e-3]
        blob = _encode_embedding(vec)
        decoded = _decode_embedding(blob)
        assert decoded.dtype == np.float32
        assert np.allclose(decoded, np.asarray(vec, dtype=np.float32))


# embed_texts_async (cache integration, mocked ORM) ------------------------


def _fake_embedding(text: str) -> EmbeddingResponse:
    seed = int.from_bytes(text.encode("utf-8")[:4].ljust(4, b"\x00"), "little")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(1536).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return EmbeddingResponse(embedding=vec.tolist(), tokens_used=0, did_truncate=False)


class TestEmbedTextsAsyncCacheLogic:
    """Cache hit/miss logic with the Postgres helpers mocked.

    The ORM round-trip is covered separately by ``TestEmbeddingCacheModel``
    so the async logic can be exercised without TransactionTestCase setup —
    mirrors the pattern in ``test_tasks.py`` (mock the IO, assert the call
    shape).
    """

    @staticmethod
    def _call(texts: list[str], cached: dict[str, np.ndarray], worker: Any) -> tuple[np.ndarray, list[int]]:
        async def _load(team, hashes, model):  # noqa: ARG001
            return cached

        async def _persist(team, content_hash, model, vector):  # noqa: ARG001
            cached[content_hash] = np.asarray(vector, dtype=np.float32)

        with (
            patch.object(intent_clustering, "_load_cached_embeddings", side_effect=_load),
            patch.object(intent_clustering, "_persist_embedding", side_effect=_persist),
            patch.object(intent_clustering, "async_generate_embedding", side_effect=worker),
        ):
            # A stub with an `id` stands in for Team — the failure-path log
            # reads team.id, and the cache IO that needs a real team is mocked.
            return asyncio.run(embed_texts_async(SimpleNamespace(id=0), texts))  # type: ignore[arg-type]

    def test_first_run_populates_cache(self) -> None:
        cached: dict[str, np.ndarray] = {}

        async def _fake_call(_team, text, model):  # noqa: ARG001
            return _fake_embedding(text)

        embeddings, valid_indices = self._call(["intent A", "intent B"], cached, _fake_call)

        assert embeddings.shape == (2, 1536)
        assert valid_indices == [0, 1]
        # Both intents persisted into the cache.
        assert set(cached.keys()) == {_content_hash("intent A"), _content_hash("intent B")}

    def test_full_cache_hit_skips_worker(self) -> None:
        # Pre-populate the cache with both intents.
        cached = {_content_hash(t): np.asarray(_fake_embedding(t).embedding, dtype=np.float32) for t in ("a", "b")}

        async def _explode(_team, _text, model):  # noqa: ARG001
            raise AssertionError("worker must not be called on cache hit")

        embeddings, valid_indices = self._call(["a", "b"], cached, _explode)

        assert valid_indices == [0, 1]
        assert embeddings.shape == (2, 1536)

    def test_partial_cache_only_embeds_missing(self) -> None:
        cached = {_content_hash("a"): np.asarray(_fake_embedding("a").embedding, dtype=np.float32)}
        worker_calls: list[str] = []

        async def _fake_call(_team, text, model):  # noqa: ARG001
            worker_calls.append(text)
            return _fake_embedding(text)

        embeddings, valid_indices = self._call(["a", "b"], cached, _fake_call)

        assert len(worker_calls) == 1
        assert worker_calls[0].endswith("b")
        assert embeddings.shape == (2, 1536)
        assert valid_indices == [0, 1]

    def test_worker_failure_skips_intent(self) -> None:
        cached: dict[str, np.ndarray] = {}

        async def _fail(_team, _text, model):  # noqa: ARG001
            raise RuntimeError("worker down")

        embeddings, valid_indices = self._call(["a", "b"], cached, _fail)

        assert valid_indices == []
        assert embeddings.shape == (0, 0)
        assert cached == {}

    def test_duplicate_texts_each_call_the_worker(self) -> None:
        # Documents intentional production behaviour: dedup happens upstream
        # (build_call_corpus aggregates by distinct intent_text), so
        # embed_texts_async itself does not dedup. If the caller passes the
        # same text twice, each call independently misses the in-memory cache
        # and hits the worker. The unique constraint on the cache row makes
        # the persist-side race harmless.
        cached: dict[str, np.ndarray] = {}
        worker_calls: list[str] = []

        async def _fake_call(_team, text, model):  # noqa: ARG001
            worker_calls.append(text)
            # Real httpx suspends here on the HTTP round-trip; the mock must
            # yield too, otherwise Task A runs to completion (including its
            # persist writeback into `cached`) before Task B's cache check
            # ever runs, and the test would observe spurious dedup that
            # doesn't happen in production.
            await asyncio.sleep(0)
            return _fake_embedding(text)

        embeddings, valid_indices = self._call(["dup", "dup"], cached, _fake_call)

        assert len(worker_calls) == 2
        assert valid_indices == [0, 1]
        assert embeddings.shape == (2, 1536)


# Cache model round-trip ----------------------------------------------------


class TestEmbeddingCacheModel(_MCPAnalyticsTeamScopedTestMixin, BaseTest):
    """Pure ORM coverage — proves the model and unique constraint work as expected."""

    def test_round_trip_via_encode_decode(self) -> None:
        vec = _fake_embedding("alpha").embedding
        MCPIntentEmbeddingCache.objects.create(
            team=self.team,
            content_hash=_content_hash("alpha"),
            model=EMBEDDING_MODEL,
            embedding=_encode_embedding(vec),
        )
        row = MCPIntentEmbeddingCache.objects.get(team=self.team, content_hash=_content_hash("alpha"))
        decoded = _decode_embedding(bytes(row.embedding))
        assert decoded.shape == (1536,)
        assert np.allclose(decoded, np.asarray(vec, dtype=np.float32))

    def test_unique_constraint_blocks_duplicate(self) -> None:
        from django.db.utils import IntegrityError

        MCPIntentEmbeddingCache.objects.create(
            team=self.team,
            content_hash="abc",
            model=EMBEDDING_MODEL,
            embedding=_encode_embedding([0.0]),
        )
        with pytest.raises(IntegrityError):
            MCPIntentEmbeddingCache.objects.create(
                team=self.team,
                content_hash="abc",
                model=EMBEDDING_MODEL,
                embedding=_encode_embedding([1.0]),
            )
