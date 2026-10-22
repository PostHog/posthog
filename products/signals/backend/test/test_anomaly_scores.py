from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.schema import (
    ChartDisplayType,
    EventPropertyFilter,
    EventsNode,
    FunnelsQuery,
    IntervalType,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.interval_specs import interval_spec
from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import DEFAULT_LIMITS, DEFAULT_PROFILE, IntervalScoring
from products.signals.backend.anomaly_scores.scoring import (
    UnsupportedInsightError,
    score_insight,
    score_series,
    trends_query_for,
)

NEW_YORK = ZoneInfo("America/New_York")
DAY_SCORING = DEFAULT_PROFILE.intervals[IntervalType.DAY]
ZSCORE_OR_KNN = IntervalScoring(
    lookback="-365d",
    min_points=56,
    detector={
        "type": "ensemble",
        "operator": "or",
        "detectors": [
            {"type": "zscore", "threshold": 0.95, "window": 56, "preprocessing": {"diffs_n": 1}},
            {"type": "knn", "threshold": 0.95},
        ],
    },
)


def _buckets(start: datetime, interval: IntervalType, count: int) -> list[datetime]:
    return [start + interval_spec(interval).period * i for i in range(count)]


class TestScoreSeries(SimpleTestCase):
    @parameterized.expand(
        [
            ("default_profile", DAY_SCORING, {"mean", "std", "value", "raw_zscore"}),
            ("ensemble", ZSCORE_OR_KNN, {"sub_scores"}),
        ]
    )
    def test_flags_the_spike_and_not_its_flat_neighbor(
        self, _name: str, scoring: IntervalScoring, detail_keys: set[str]
    ) -> None:
        values = list(np.random.default_rng(0).normal(100, 5, size=120))
        values[110] = 400.0
        buckets = _buckets(datetime(2026, 1, 1, tzinfo=NEW_YORK), IntervalType.DAY, 120)

        points = score_series(
            values,
            buckets,
            scoring=scoring,
            interval=IntervalType.DAY,
            now=buckets[-1] + timedelta(hours=12),
        )

        by_bucket = {point.bucket_start: point for point in points}
        assert by_bucket[buckets[110]].flag is True
        assert by_bucket[buckets[109]].flag is False
        assert set(by_bucket[buckets[110]].details) == detail_keys
        assert len(points) == DEFAULT_LIMITS.max_backfill_buckets

    @parameterized.expand(
        [
            ("hour", IntervalType.HOUR, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 1, 4, 30, tzinfo=UTC), 3),
            ("day", IntervalType.DAY, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 5, 23, tzinfo=UTC), 3),
            ("week", IntervalType.WEEK, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 29, 1, tzinfo=UTC), 3),
            # 03:00 UTC on Feb 1 is still January in New York, so January is ongoing.
            (
                "month_boundary_new_york",
                IntervalType.MONTH,
                datetime(2025, 9, 1, tzinfo=NEW_YORK),
                datetime(2026, 2, 1, 3, tzinfo=UTC),
                3,
            ),
            (
                "month_after_boundary_new_york",
                IntervalType.MONTH,
                datetime(2025, 9, 1, tzinfo=NEW_YORK),
                datetime(2026, 2, 1, 6, tzinfo=UTC),
                4,
            ),
        ]
    )
    def test_never_returns_the_ongoing_bucket(
        self, _name: str, interval: IntervalType, start: datetime, now: datetime, last_completed: int
    ) -> None:
        buckets = _buckets(start, interval, 6)
        buckets = [bucket for bucket in buckets if bucket <= now]

        points = score_series(
            [1.0] * len(buckets), buckets, scoring=DEFAULT_PROFILE.intervals[interval], interval=interval, now=now
        )

        assert points[-1].bucket_start == buckets[last_completed]

    def test_warm_up_points_have_no_score_and_no_flag(self) -> None:
        buckets = _buckets(datetime(2026, 1, 1, tzinfo=UTC), IntervalType.DAY, 10)

        points = score_series(
            [1.0, 2.0, 1.0, 50.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0],
            buckets,
            scoring=DAY_SCORING,
            interval=IntervalType.DAY,
            now=buckets[-1] + timedelta(days=1),
        )

        assert len(points) == 10
        assert all(point.score is None and point.flag is None for point in points)


def _insight(series: list[EventsNode], **query: Any) -> Insight:
    return Insight(id=7, query=TrendsQuery(series=series, **query).model_dump(exclude_none=True))


def _result(order: int, label: str) -> dict[str, Any]:
    days = [f"2026-01-{day:02d}" for day in range(1, 6)]
    return {"action": {"order": order}, "label": label, "days": days, "data": [1.0] * 5, "breakdown_value": None}


class TestScoreInsight(SimpleTestCase):
    def _keys(self, insight: Insight, results: list[dict[str, Any]]) -> dict[str, str]:
        with patch(
            "products.signals.backend.anomaly_scores.scoring.calculate_for_query_based_insight",
            return_value=MagicMock(result=results),
        ):
            scores = score_insight(insight, Team(timezone="UTC"), now=datetime(2026, 1, 10, tzinfo=UTC))
        return {series.label: series.series_key for series in scores.series}

    def test_series_key_follows_the_series_definition_not_its_position(self) -> None:
        pageview = EventsNode(event="$pageview")
        signup = EventsNode(event="signed_up")
        chrome_pageview = EventsNode(
            event="$pageview",
            properties=[EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)],
        )

        original = self._keys(_insight([pageview, signup]), [_result(0, "pageview"), _result(1, "signup")])
        swapped = self._keys(_insight([signup, pageview]), [_result(0, "signup"), _result(1, "pageview")])
        filtered = self._keys(_insight([chrome_pageview, signup]), [_result(0, "pageview"), _result(1, "signup")])

        assert swapped == original
        assert filtered["signup"] == original["signup"]
        assert filtered["pageview"] != original["pageview"]


class TestTrendsQueryFor(SimpleTestCase):
    @parameterized.expand(
        [
            ("funnel", FunnelsQuery(series=[EventsNode(event="$pageview")]).model_dump(exclude_none=True)),
            (
                "single_value",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                ).model_dump(exclude_none=True),
            ),
            (
                "cumulative",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE),
                ).model_dump(exclude_none=True),
            ),
            (
                "minute_interval",
                TrendsQuery(series=[EventsNode(event="$pageview")], interval=IntervalType.MINUTE).model_dump(
                    exclude_none=True
                ),
            ),
        ]
    )
    def test_unsupported_shapes_raise(self, _name: str, query: dict[str, Any]) -> None:
        with self.assertRaises(UnsupportedInsightError):
            trends_query_for(Insight(id=1, query=query), DEFAULT_PROFILE)
