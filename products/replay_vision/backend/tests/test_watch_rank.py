from datetime import UTC, datetime, timedelta
from typing import Any

from unittest.mock import patch

from django.db.models import Q
from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.exceptions import ClickHouseAtCapacity

from products.replay_vision.backend import watch_rank_backfill
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.watch_feed import SESSION_SPACING
from products.replay_vision.backend.watch_rank import (
    ANCHOR_VERSION,
    WatchCategory,
    classify,
    duplicate_root,
    rank_watch_feed_by_embedding,
)
from products.replay_vision.backend.watch_rank_backfill import _rank_scanner, _RecentVectors, _stored_vectors

_NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _row(
    observation_id: str,
    contrast: float | None,
    *,
    category: str = "failure",
    scanner: str = "scanner-a",
    duplicate_of: str | None = None,
    anchor_version: int = ANCHOR_VERSION,
    minutes_ago: int = 0,
    viewed: bool = False,
    session: str | None = None,
) -> dict[str, Any]:
    rank = (
        None
        if contrast is None
        else {
            "category": category,
            "contrast": contrast,
            "duplicate_of": duplicate_of,
            "anchor_version": anchor_version,
        }
    )
    return {
        "id": observation_id,
        "scanner_id": scanner,
        "session_id": session or f"session-{observation_id}",
        "created_at": _NOW - timedelta(minutes=minutes_ago),
        "watch_rank": rank,
        "feed_viewed": viewed,
    }


class TestClassify(SimpleTestCase):
    @parameterized.expand(
        [
            ("closest_to_an_issue", [1.0, 0.1, 0.0], "failure", True),
            ("closest_to_routine", [0.1, 0.0, 1.0], "routine", False),
        ]
    )
    def test_routine_wins_over_the_closest_issue_when_it_is_closer(
        self, _name: str, vector: list[float], category: str, positive: bool
    ) -> None:
        anchors: dict[WatchCategory, np.ndarray] = {
            "failure": np.array([[1.0, 0.0, 0.0]]),
            "struggle": np.array([[0.0, 1.0, 0.0]]),
            "revenue": np.array([[0.0, -1.0, 0.0]]),
            "routine": np.array([[0.0, 0.0, 1.0]]),
        }
        got_category, contrast = classify(vector, anchors)
        assert got_category == category
        assert (contrast > 0) is positive


class TestPickIndexes(SimpleTestCase):
    @parameterized.expand([("rlo_ranked_count_idx",), ("rlo_ranked_contrast_idx",)])
    def test_pick_index_matches_the_current_anchor_version(self, name: str) -> None:
        index = next(index for index in ReplayObservation._meta.indexes if index.name == name)
        assert index.condition == Q(
            status="succeeded", watch_rank__isnull=False, watch_rank__anchor_version=ANCHOR_VERSION
        )


class TestDuplicateRoot(SimpleTestCase):
    @parameterized.expand(
        [
            ("unranked_smaller_neighbour_is_the_root", "obs-b", "obs-a", None, "obs-a"),
            ("unranked_larger_neighbour_defers_to_this_one", "obs-a", "obs-b", None, None),
            ("ranked_neighbour_passes_on_its_root", "obs-a", "obs-b", {"duplicate_of": "obs-0"}, "obs-0"),
            ("ranked_root_neighbour_is_the_root", "obs-a", "obs-b", {"duplicate_of": None}, "obs-b"),
        ]
    )
    def test_two_concurrent_copies_agree_on_one_root(
        self,
        _name: str,
        observation_id: str,
        neighbour_id: str,
        neighbour_rank: dict[str, Any] | None,
        expected: str | None,
    ) -> None:
        assert duplicate_root(observation_id, neighbour_id, neighbour_rank) == expected


class TestRankWatchFeedByEmbedding(SimpleTestCase):
    def test_a_finding_that_reached_more_people_outranks_a_stronger_one_off(self) -> None:
        rows = [_row(f"a-{index}", 0.01 * index, minutes_ago=index + 1) for index in range(10)]
        rows += [_row("one-off", 0.9), _row("widespread", 0.5)]
        # Window percentiles and group reach, as the whole-window pick query supplies them.
        for row in rows:
            row["watch_percentile"] = {"one-off": 0.99, "widespread": 0.85}.get(str(row["id"]))
            row["watch_group_people"] = 6 if row["id"] == "widespread" else 1
        ranked = rank_watch_feed_by_embedding(rows)
        assert [entry.observation_id for entry in ranked][:2] == ["widespread", "one-off"]
        assert ranked[0].reason["affected_people"] == 6

    def test_picks_the_scanner_top_issues_once_per_duplicate_group(self) -> None:
        rows = [
            # scanner-a has enough ranked rows for a percentile; its top two are one duplicate group.
            _row("dup-root", 0.30),
            _row("dup-copy", 0.32, duplicate_of="dup-root", minutes_ago=50),
            _row("dup-low", -0.01, duplicate_of="dup-root"),
            # A copy that points at another copy, as when its root was ranked after it, still joins the group.
            _row("dup-chain", 0.02, duplicate_of="dup-copy", minutes_ago=3),
            _row("routine-top", 0.40, category="routine", minutes_ago=50),
            *[_row(f"a-{index}", 0.01 * index, minutes_ago=index + 1) for index in range(10)],
            # A rank from older anchors does not compare with current scores.
            _row("stale", 0.90, anchor_version=ANCHOR_VERSION - 1),
            # scanner-b is too thin for a percentile, so its top row is only filler.
            _row("b-top", 0.50, scanner="scanner-b", minutes_ago=1),
        ]

        ranked = rank_watch_feed_by_embedding(rows)

        assert ranked[0].observation_id == "dup-copy"
        assert ranked[0].reason == {
            "kind": "embedding_pick",
            "watch_category": "failure",
            "similar_count": 3,
            "affected_people": 1,
        }
        picks = [entry.observation_id for entry in ranked if entry.reason["kind"] == "embedding_pick"]
        assert picks == ["dup-copy"]
        # Collapsed copies, even those below the cutoff, must not come back as filler.
        assert {"dup-root", "dup-low", "dup-chain"}.isdisjoint(entry.observation_id for entry in ranked)

    def test_a_viewed_pick_still_stands_for_its_group_over_a_copy_below_the_cutoff(self) -> None:
        rows = [
            _row("seen-top", 0.9, viewed=True),
            _row("other-top", 0.8, minutes_ago=1),
            _row("mid-copy", 0.7, duplicate_of="seen-top", minutes_ago=2),
            *[_row(f"a-{index}", 0.01 * index, minutes_ago=index + 3) for index in range(7)],
        ]

        ranked = rank_watch_feed_by_embedding(rows)

        picks = {
            str(entry.observation_id): entry.reason for entry in ranked if entry.reason["kind"] == "embedding_pick"
        }
        assert picks["seen-top"]["similar_count"] == 1
        assert "mid-copy" not in {entry.observation_id for entry in ranked}

    def test_two_scanners_picking_one_session_land_apart_without_dropping_a_pick(self) -> None:
        rows = [
            _row(f"{scanner}-{index}", index / 20, scanner=scanner, minutes_ago=index)
            for scanner in ("scanner-a", "scanner-b", "scanner-c")
            for index in range(9)
        ] + [
            _row("a-top", 0.9, scanner="scanner-a", session="shared"),
            _row("b-top", 0.9, scanner="scanner-b", session="shared", minutes_ago=1),
            _row("c-top", 0.9, scanner="scanner-c", minutes_ago=2),
        ]

        ranked = [str(entry.observation_id) for entry in rank_watch_feed_by_embedding(rows)]

        assert ranked[0] == "a-top"
        assert ranked.index("b-top") - ranked.index("a-top") >= SESSION_SPACING
        assert {"a-top", "b-top", "c-top", "scanner-a-8", "scanner-b-8", "scanner-c-8"} <= set(ranked)

    def test_rows_without_a_rank_fall_back_to_the_filler_floor(self) -> None:
        rows = [_row(f"row-{index}", None, minutes_ago=index, viewed=index == 0) for index in range(20)]

        ranked = rank_watch_feed_by_embedding(rows)

        assert [entry.observation_id for entry in ranked] == ["row-1", "row-2", "row-3"]


class TestBackfillRankScanner(SimpleTestCase):
    def test_walks_oldest_first_so_a_copy_joins_the_group_of_an_already_ranked_row(self) -> None:
        anchors: dict[WatchCategory, np.ndarray] = {
            "failure": np.array([[1.0, 0.0, 0.0]]),
            "struggle": np.array([[0.0, 1.0, 0.0]]),
            "revenue": np.array([[0.0, -1.0, 0.0]]),
            "routine": np.array([[0.0, 0.0, 1.0]]),
        }
        error = np.array([1.0, 0.0, 0.0])
        current = {"category": "failure", "contrast": 1.0, "duplicate_of": "root", "anchor_version": ANCHOR_VERSION}
        rows: list[dict[str, Any]] = [
            {"id": "ranked", "watch_rank": current},
            {"id": "no-vector", "watch_rank": None},
            {"id": "copy", "watch_rank": None},
            {"id": "stale", "watch_rank": {**current, "anchor_version": ANCHOR_VERSION - 1}},
            {"id": "calm", "watch_rank": None},
        ]
        vectors = {"ranked": error, "copy": error, "stale": error, "calm": np.array([0.0, 0.0, 1.0])}

        # Two batches that share the recent vectors, as the backfill runs them.
        recent = _RecentVectors()
        written = {
            **_rank_scanner(rows[:2], vectors, anchors, recent),
            **_rank_scanner(rows[2:], vectors, anchors, recent),
        }

        assert set(written) == {"copy", "stale", "calm"}
        assert written["copy"]["duplicate_of"] == "root"
        assert written["stale"]["duplicate_of"] == "root"
        assert written["calm"]["category"] == "routine"
        assert written["calm"]["duplicate_of"] is None

    @parameterized.expand(
        [
            ("cluster_frees_up", 2, {"obs-1"}),
            ("cluster_stays_full", 99, None),
        ]
    )
    def test_vector_read_waits_out_a_cluster_at_capacity(
        self, _name: str, refusals: int, expected: set[str] | None
    ) -> None:
        calls = 0

        def execute(*args: Any, **kwargs: Any) -> list[tuple[str, list[float]]]:
            nonlocal calls
            calls += 1
            if calls <= refusals:
                raise ClickHouseAtCapacity()
            return [("obs-1", [1.0, 0.0, 0.0])]

        with (
            patch.object(watch_rank_backfill, "sync_execute", side_effect=execute),
            patch.object(watch_rank_backfill.time, "sleep") as sleep,
        ):
            if expected is None:
                with self.assertRaises(ClickHouseAtCapacity):
                    _stored_vectors(2, "scanner-a", ["obs-1"], _NOW)
                assert calls == watch_rank_backfill._CAPACITY_RETRY_ATTEMPTS
            else:
                assert set(_stored_vectors(2, "scanner-a", ["obs-1"], _NOW)) == expected
                assert sleep.call_count == refusals
