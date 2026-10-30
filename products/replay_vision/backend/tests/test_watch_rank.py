import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.exceptions import ClickHouseAtCapacity

from products.replay_vision.backend import watch_rank_backfill
from products.replay_vision.backend.highlight_feed import PERSON_SPACING
from products.replay_vision.backend.tests.helpers import axis_anchors
from products.replay_vision.backend.watch_rank import (
    ANCHOR_VERSION,
    ANCHORS,
    HIGHLIGHT_PICK_MIN_SCANNER_ROWS,
    classify,
    rank_highlight_feed_by_embedding,
)
from products.replay_vision.backend.watch_rank_backfill import _rank_scanner, _stored_vectors

_NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _row(
    observation_id: str,
    contrast: float | None,
    *,
    category: str = "failure",
    scanner: str = "scanner-a",
    group: str | None = None,
    anchor_version: int = ANCHOR_VERSION,
    minutes_ago: int = 0,
    viewed: bool = False,
    person: int | None = None,
) -> dict[str, Any]:
    current = contrast is not None and anchor_version == ANCHOR_VERSION
    return {
        "id": observation_id,
        "scanner_id": scanner,
        "person_key": person if person is not None else zlib.crc32(observation_id.encode()),
        "created_at": _NOW - timedelta(minutes=minutes_ago),
        "feed_viewed": viewed,
        "contrast": contrast if current else None,
        "watch_category": category if current else None,
        "watch_group_root": group or observation_id,
    }


def _with_percentiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row's contrast percentile within its scanner, as a stored build attaches it."""
    by_scanner: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["contrast"] is not None:
            by_scanner.setdefault(row["scanner_id"], []).append(row)
    for scanner_rows in by_scanner.values():
        if len(scanner_rows) < HIGHLIGHT_PICK_MIN_SCANNER_ROWS:
            continue
        scanner_rows.sort(key=lambda row: row["contrast"])
        for position, row in enumerate(scanner_rows):
            row.setdefault("watch_percentile", (position + 0.5) / len(scanner_rows))
    return rows


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
        anchors = axis_anchors()
        reading = classify(vector, anchors)
        assert reading.rank.category == category
        assert (reading.rank.contrast > 0) is positive
        assert set(reading.similarities) == {key for texts in ANCHORS.values() for key in texts}


class TestRankHighlightFeedByEmbedding(SimpleTestCase):
    def test_a_finding_that_reached_more_people_outranks_a_stronger_one_off(self) -> None:
        rows = [_row(f"a-{index}", 0.01 * index, minutes_ago=index + 1) for index in range(10)]
        rows += [_row("one-off", 0.9), _row("widespread", 0.5)]
        # Window percentiles and group reach, as a stored build supplies them.
        for row in rows:
            row["watch_percentile"] = {"one-off": 0.99, "widespread": 0.85}.get(str(row["id"]))
            row["watch_group_people"] = 6 if row["id"] == "widespread" else 1
        ranked = rank_highlight_feed_by_embedding(_with_percentiles(rows))
        assert [entry.observation_id for entry in ranked][:2] == ["widespread", "one-off"]
        assert ranked[0].reason["affected_people"] == 6

    def test_picks_the_scanner_top_issues_once_per_feed_group(self) -> None:
        rows = [
            # scanner-a has enough ranked rows for a percentile; its top two are one feed group.
            _row("dup-root", 0.30, group="g1"),
            _row("dup-copy", 0.32, group="g1", minutes_ago=50),
            _row("dup-low", -0.01, group="g1"),
            _row("dup-chain", 0.02, group="g1", minutes_ago=3),
            _row("routine-top", 0.40, category="routine", minutes_ago=50),
            *[_row(f"a-{index}", 0.01 * index, minutes_ago=index + 1) for index in range(10)],
            # A rank from older anchors does not compare with current scores.
            _row("stale", 0.90, anchor_version=ANCHOR_VERSION - 1),
            # scanner-b is too thin for a percentile, so its top row is only filler.
            _row("b-top", 0.50, scanner="scanner-b", minutes_ago=1),
        ]

        ranked = rank_highlight_feed_by_embedding(_with_percentiles(rows))

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
            _row("seen-top", 0.9, viewed=True, group="g1"),
            _row("other-top", 0.8, minutes_ago=1),
            _row("mid-copy", 0.7, group="g1", minutes_ago=2),
            *[_row(f"a-{index}", 0.01 * index, minutes_ago=index + 3) for index in range(7)],
        ]

        ranked = rank_highlight_feed_by_embedding(_with_percentiles(rows))

        picks = {
            str(entry.observation_id): entry.reason for entry in ranked if entry.reason["kind"] == "embedding_pick"
        }
        assert picks["seen-top"]["similar_count"] == 1
        assert "mid-copy" not in {entry.observation_id for entry in ranked}

    def test_two_scanners_picking_one_person_land_apart_without_dropping_a_pick(self) -> None:
        rows = [
            _row(f"{scanner}-{index}", index / 20, scanner=scanner, minutes_ago=index)
            for scanner in ("scanner-a", "scanner-b", "scanner-c")
            for index in range(9)
        ] + [
            _row("a-top", 0.9, scanner="scanner-a", person=7),
            _row("b-top", 0.9, scanner="scanner-b", person=7, minutes_ago=1),
            _row("c-top", 0.9, scanner="scanner-c", minutes_ago=2),
        ]

        ranked = [str(entry.observation_id) for entry in rank_highlight_feed_by_embedding(_with_percentiles(rows))]

        assert ranked[0] == "a-top"
        assert ranked.index("b-top") - ranked.index("a-top") >= PERSON_SPACING
        assert {"a-top", "b-top", "c-top", "scanner-a-8", "scanner-b-8", "scanner-c-8"} <= set(ranked)

    def test_rows_without_a_rank_fall_back_to_the_filler_floor(self) -> None:
        rows = [_row(f"row-{index}", None, minutes_ago=index, viewed=index == 0) for index in range(20)]

        ranked = rank_highlight_feed_by_embedding(_with_percentiles(rows))

        assert [entry.observation_id for entry in ranked] == ["row-1", "row-2", "row-3"]


class TestBackfillRankScanner(SimpleTestCase):
    def test_ranks_only_rows_without_a_current_rank(self) -> None:
        anchors = axis_anchors()
        error = np.array([1.0, 0.0, 0.0])
        rows: list[dict[str, Any]] = [
            {"id": "ranked", "ranked": True},
            {"id": "no-vector", "ranked": False},
            {"id": "copy", "ranked": False},
            {"id": "calm", "ranked": False},
        ]
        vectors = {"ranked": error, "copy": error, "calm": np.array([0.0, 0.0, 1.0])}

        written = _rank_scanner(rows, vectors, anchors)

        assert set(written) == {"copy", "calm"}
        assert written["copy"].rank.category == "failure"
        assert written["calm"].rank.category == "routine"

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
