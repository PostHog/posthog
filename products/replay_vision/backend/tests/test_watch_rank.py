from datetime import UTC, datetime, timedelta
from typing import Any

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from products.replay_vision.backend.watch_rank import ANCHOR_VERSION, classify, rank_watch_feed_by_embedding

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
        anchors = {
            "failure": np.array([[1.0, 0.0, 0.0]]),
            "struggle": np.array([[0.0, 1.0, 0.0]]),
            "revenue": np.array([[0.0, -1.0, 0.0]]),
            "routine": np.array([[0.0, 0.0, 1.0]]),
        }
        got_category, contrast = classify(vector, anchors)
        assert got_category == category
        assert (contrast > 0) is positive


class TestRankWatchFeedByEmbedding(SimpleTestCase):
    def test_picks_the_scanner_top_issues_once_per_duplicate_group(self) -> None:
        rows = [
            # scanner-a has enough ranked rows for a percentile; its top two are one duplicate group.
            _row("dup-root", 0.30),
            _row("dup-copy", 0.32, duplicate_of="dup-root", minutes_ago=50),
            _row("routine-top", 0.40, category="routine", minutes_ago=50),
            *[_row(f"a-{index}", 0.01 * index, minutes_ago=index + 1) for index in range(10)],
            # A rank from older anchors does not compare with current scores.
            _row("stale", 0.90, anchor_version=ANCHOR_VERSION - 1),
            # scanner-b is too thin for a percentile, so its top row is only filler.
            _row("b-top", 0.50, scanner="scanner-b", minutes_ago=1),
        ]

        ranked = rank_watch_feed_by_embedding(rows)

        assert ranked[0].observation_id == "dup-copy"
        assert ranked[0].reason == {"kind": "embedding_pick", "watch_category": "failure", "similar_count": 1}
        picks = [entry.observation_id for entry in ranked if entry.reason["kind"] == "embedding_pick"]
        assert picks == ["dup-copy"]
        # The newest row is the collapsed copy, which must not come back as filler.
        assert "dup-root" not in {entry.observation_id for entry in ranked}

    def test_rows_without_a_rank_fall_back_to_the_filler_floor(self) -> None:
        rows = [_row(f"row-{index}", None, minutes_ago=index, viewed=index == 0) for index in range(20)]

        ranked = rank_watch_feed_by_embedding(rows)

        assert [entry.observation_id for entry in ranked] == ["row-1", "row-2", "row-3"]
