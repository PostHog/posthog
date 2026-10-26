from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import IntervalType

from products.signals.backend.anomaly_scores.selection import (
    Candidate,
    InsightUsage,
    SelectionConfig,
    Weighting,
    parse_selection_config,
    pick_order,
    staleness,
)

TICK = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
MAX_STALENESS = 30
WEIGHTED = SelectionConfig()
UNIFORM = SelectionConfig(weighting=Weighting.UNIFORM)


def _candidate(
    insight_id: int,
    *,
    days_since_scored: int | None,
    viewers: int = 0,
    alert: bool = False,
    interval: IntervalType = IntervalType.DAY,
) -> Candidate:
    newest = (
        None if days_since_scored is None else datetime(2026, 10, 15, tzinfo=UTC) - timedelta(days=days_since_scored)
    )
    return Candidate(
        insight_id=insight_id,
        interval=interval,
        newest_scored_bucket=newest,
        usage=InsightUsage(viewers=viewers, has_enabled_alert=alert),
    )


class TestPickOrder(SimpleTestCase):
    @parameterized.expand(
        [
            # (usage 1 × staleness 1) vs (usage 4 × staleness 1)
            ("viewers", {"days_since_scored": 2}, {"days_since_scored": 2, "viewers": 3}, 0.8),
            # (1 × 1) vs ((1 + 5) × 1)
            ("enabled_alert", {"days_since_scored": 2}, {"days_since_scored": 2, "alert": True}, 6 / 7),
            # A popular insight scored recently, (10 × 1), against a long-waiting unviewed one, (1 × 29).
            ("waiting_overtakes_usage", {"days_since_scored": 2, "viewers": 9}, {"days_since_scored": 30}, 29 / 39),
            # Staleness is capped, and a never-scored insight counts as the cap.
            ("capped_staleness", {"days_since_scored": None}, {"days_since_scored": 90}, 0.5),
        ]
    )
    def test_first_pick_rate_follows_weight(
        self, _name: str, low: dict[str, Any], high: dict[str, Any], expected_high_rate: float
    ) -> None:
        candidates = [_candidate(1, **low), _candidate(2, **high)]
        first_picks = Counter(
            pick_order(
                candidates, config=WEIGHTED, tick_start=TICK + timedelta(seconds=i), max_staleness=MAX_STALENESS
            )[0]
            for i in range(4000)
        )

        assert abs(first_picks[2] / 4000 - expected_high_rate) < 0.03

    def test_uniform_picks_never_scored_then_stalest(self) -> None:
        candidates = [
            _candidate(1, days_since_scored=3, viewers=50),
            _candidate(2, days_since_scored=None),
            _candidate(3, days_since_scored=10),
            _candidate(4, days_since_scored=None, viewers=50),
        ]

        order = pick_order(candidates, config=UNIFORM, tick_start=TICK, max_staleness=MAX_STALENESS)

        assert set(order[:2]) == {2, 4}
        assert order[2:] == [3, 1]

    @parameterized.expand(
        [
            ("nothing_completed_weighted", WEIGHTED, {"days_since_scored": 1, "viewers": 50}),
            ("nothing_completed_uniform", UNIFORM, {"days_since_scored": 1, "viewers": 50}),
            ("unviewed_without_floor", SelectionConfig(usage_floor=0), {"days_since_scored": None}),
        ]
    )
    def test_leaves_out_candidates_with_nothing_to_gain(
        self, _name: str, config: SelectionConfig, excluded: dict[str, Any]
    ) -> None:
        candidates = [_candidate(1, **excluded), _candidate(2, days_since_scored=5, viewers=1)]

        assert pick_order(candidates, config=config, tick_start=TICK, max_staleness=MAX_STALENESS) == [2]

    @parameterized.expand(
        [
            # Oct 14 is ongoing at noon, so only Oct 12 and Oct 13 are completed.
            ("day", IntervalType.DAY, datetime(2026, 10, 11, tzinfo=UTC), 2),
            ("month", IntervalType.MONTH, datetime(2026, 7, 1, tzinfo=UTC), 2),
            ("capped", IntervalType.HOUR, datetime(2026, 10, 1, tzinfo=UTC), MAX_STALENESS),
        ]
    )
    def test_staleness_counts_completed_buckets_after_the_newest_scored_one(
        self, _name: str, interval: IntervalType, newest_scored_bucket: datetime, expected: int
    ) -> None:
        candidate = Candidate(
            insight_id=1,
            interval=interval,
            newest_scored_bucket=newest_scored_bucket,
            usage=InsightUsage(viewers=0, has_enabled_alert=False),
        )

        assert staleness(candidate, now=datetime(2026, 10, 14, 12, tzinfo=UTC), max_staleness=MAX_STALENESS) == expected


class TestParseSelectionConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", None, SelectionConfig()),
            (
                "valid",
                {"weighting": "uniform", "usage_floor": 0, "alert_bonus": 10},
                SelectionConfig(weighting=Weighting.UNIFORM, usage_floor=0, alert_bonus=10),
            ),
            (
                "invalid_fields_fall_back",
                {"weighting": "random", "usage_floor": -1, "alert_bonus": True},
                SelectionConfig(),
            ),
        ]
    )
    def test_parse(self, _name: str, payload: Any, expected: SelectionConfig) -> None:
        assert parse_selection_config(payload) == expected
