import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.schema import (
    ChartDisplayType,
    CompareFilter,
    EventPropertyFilter,
    EventsNode,
    FunnelsQuery,
    IntervalType,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.constants import INSIGHT_QUERY_FANOUT_CONCURRENCY

from posthog.interval_specs import interval_spec
from posthog.models import Team
from posthog.tasks.alerts.detectors.registry import get_detector

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.artifacts import deserialize, serialize
from products.signals.backend.anomaly_scores.config import DEFAULT_LIMITS, DEFAULT_PROFILE, IntervalScoring, ScoringRun
from products.signals.backend.anomaly_scores.scoring import (
    InsightScores,
    SplitRun,
    StateIdentity,
    TrainedState,
    UnsupportedInsightError,
    bucket_end,
    buckets_to_score,
    fetch_buckets,
    history_buckets,
    query_cost,
    score_insight,
    score_series,
    trends_query_for,
)
from products.signals.backend.anomaly_scores.state import TrainDue, train_due
from products.signals.backend.anomaly_scores.tick import _INSIGHT_TIMEOUT

NEW_YORK = ZoneInfo("America/New_York")
DAY_SCORING = DEFAULT_PROFILE.intervals[IntervalType.DAY]
ZSCORE_OR_KNN = IntervalScoring(
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

    @parameterized.expand(
        [
            ("first_score", None, DEFAULT_LIMITS.max_backfill_buckets, None),
            ("revisit", 3, 3, None),
            ("chart_smoothing", 3, 3, 7),
        ]
    )
    def test_the_fetched_buckets_score_like_the_full_history(
        self, _name: str, scored_days_ago: int | None, to_score: int, smoothing: int | None
    ) -> None:
        values = list(np.random.default_rng(1).normal(100, 20, size=365))
        buckets = _buckets(datetime(2025, 10, 1, tzinfo=UTC), IntervalType.DAY, 365)
        now = buckets[-1] + timedelta(days=1, hours=1)
        after = None if scored_days_ago is None else buckets[-1 - scored_days_ago]
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], trendsFilter=TrendsFilter(smoothingIntervals=smoothing)
        )

        assert buckets_to_score(IntervalType.DAY, now=now, after=after, timezone=ZoneInfo("UTC")) == to_score
        fetched = fetch_buckets(query, DAY_SCORING, to_score)

        def score(start: int) -> list[float | None]:
            fetched_values = values[start:]
            if smoothing:
                # Trends averages the trailing buckets that the query fetched, so the fetch start shifts the average.
                fetched_values = [
                    float(np.floor(np.mean(fetched_values[max(0, i - smoothing + 1) : i + 1])))
                    for i in range(len(fetched_values))
                ]
            points = score_series(
                fetched_values,
                buckets[start:],
                scoring=DAY_SCORING,
                interval=IntervalType.DAY,
                now=now,
                after=after,
            )
            return [point.score for point in points]

        assert fetched < 100
        assert score(-fetched) == score(0)
        assert None not in score(-fetched)

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


class TestArtifactRoundTrip(SimpleTestCase):
    @parameterized.expand(
        [
            ("json_params", DAY_SCORING.detector),
            ("pyod_model_bytes", {"type": "knn", "threshold": 0.95, "preprocessing": {"diffs_n": 1, "lags_n": 5}}),
        ]
    )
    def test_a_stored_artifact_scores_like_the_fitted_one(self, _name: str, config: dict[str, Any]) -> None:
        detector = get_detector(config)
        data = np.random.default_rng(2).normal(100, 10, size=100)
        data[-1] = 400.0
        artifact = detector.fit(data[:90])
        scored = data[90 - detector.context_buckets() :]

        loaded = deserialize(serialize({"series": artifact}))["series"]

        assert loaded == artifact
        assert detector.score(loaded, scored).all_scores == detector.score(artifact, scored).all_scores


def _insight(series: list[EventsNode], **query: Any) -> Insight:
    return Insight(id=7, query=TrendsQuery(series=series, **query).model_dump(exclude_none=True))


def _result(order: int, label: str) -> dict[str, Any]:
    days = [f"2026-01-{day:02d}" for day in range(1, 6)]
    return {"order": order, "label": label, "days": days, "data": [1.0] * 5, "breakdown_value": None}


class TestScoreInsight(SimpleTestCase):
    def _keys(self, insight: Insight, results: list[dict[str, Any]]) -> dict[str, str]:
        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.run.return_value = MagicMock(results=results)
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

    def test_series_that_differ_only_by_name_get_unique_keys_and_the_first_keeps_its_key(self) -> None:
        single = self._keys(_insight([EventsNode(event="$pageview")]), [_result(0, "web")])
        named = self._keys(
            _insight(
                [EventsNode(event="$pageview", custom_name="web"), EventsNode(event="$pageview", custom_name="app")]
            ),
            [_result(0, "web"), _result(1, "app")],
        )

        assert named["web"] == single["web"]
        assert named["app"] != named["web"]

    def test_previous_period_lines_are_not_scored_and_the_current_line_keeps_its_key(self) -> None:
        pageview = EventsNode(event="$pageview")
        line = self._keys(_insight([pageview]), [_result(0, "pageview")])
        metric = self._keys(
            _insight([pageview], trendsFilter=TrendsFilter(display=ChartDisplayType.METRIC)),
            [
                {**_result(0, "pageview"), "compare_label": "current"},
                {**_result(0, "pageview"), "compare_label": "previous"},
            ],
        )

        assert metric == line

    @parameterized.expand([("one_query", 1), ("one_full_wave", 10), ("two_waves", 11), ("many_waves", 120)])
    def test_every_query_wave_of_an_insight_stops_before_the_activity_timeout(self, _name: str, queries: int) -> None:
        limits: list[int] = []
        insight = _insight([EventsNode(event=f"event_{index}") for index in range(queries)])
        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.series = [object()] * queries

            def run(**_kwargs: Any) -> MagicMock:
                limits.append(runner.return_value.hogql_settings.max_execution_time)
                return MagicMock(results=[])

            runner.return_value.run.side_effect = run
            score_insight(insight, Team(timezone="UTC"), now=datetime(2026, 1, 10, tzinfo=UTC))

        waves = -(-queries // INSIGHT_QUERY_FANOUT_CONCURRENCY)
        # Each wave can run to the time limit, and the activity still needs time to classify the timeout.
        assert timedelta(seconds=waves * limits[0]) <= _INSIGHT_TIMEOUT - timedelta(minutes=1)
        if waves == 1:
            assert limits[0] == 150

    # The context of the day detector is 3 buckets, then one guard bucket and the 2 new buckets.
    @parameterized.expand([("no_smoothing", None, "-6d"), ("smoothing", 7, "-12d")])
    def test_a_score_step_fetches_only_the_context_and_new_buckets(
        self, _name: str, smoothing: int | None, date_from: str
    ) -> None:
        insight = _insight([EventsNode(event="$pageview")], trendsFilter=TrendsFilter(smoothingIntervals=smoothing))
        team = Team(timezone="UTC")
        rng = np.random.default_rng(3)

        def result(breakdown: str, first_day: datetime, days: int) -> dict[str, Any]:
            return {
                "order": 0,
                "label": "pageview",
                "breakdown_value": breakdown,
                "days": [(first_day + timedelta(days=day)).strftime("%Y-%m-%d") for day in range(days)],
                "data": list(rng.normal(100, 10, size=days)),
            }

        def run(now: datetime, results: list[dict[str, Any]], split: SplitRun) -> tuple[InsightScores, TrendsQuery]:
            with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
                runner.return_value.run.return_value = MagicMock(results=results)
                scores = score_insight(insight, team, now=now, split=split)
            return scores, runner.call_args.kwargs["query"]

        trained, _query = run(
            datetime(2026, 1, 10, 0, 30, tzinfo=UTC),
            [
                result("kept", datetime(2025, 10, 1, tzinfo=UTC), 102),
                result("gone", datetime(2025, 10, 1, tzinfo=UTC), 102),
            ],
            SplitRun(),
        )
        assert trained.run == ScoringRun.TRAIN and trained.state is not None and trained.artifacts is not None
        assert set(trained.state.series_keys) == {series.series_key for series in trained.series}
        state = dataclasses.replace(trained.state, artifact_key="anomaly_models/1/7/default-v1/model")

        scores, query = run(
            datetime(2026, 1, 12, 0, 30, tzinfo=UTC),
            [result("kept", datetime(2026, 1, 6, tzinfo=UTC), 7), result("new", datetime(2026, 1, 6, tzinfo=UTC), 7)],
            SplitRun(state=state, artifacts=trained.artifacts),
        )

        assert query.dateRange is not None and query.dateRange.date_from == date_from
        assert scores.run == ScoringRun.SCORE
        assert [
            (series.breakdown_value, [point.bucket_start.day for point in series.points]) for series in scores.series
        ] == [("kept", [10, 11])]
        assert all(point.score is not None for point in scores.series[0].points)
        assert scores.unmatched_series == 1
        assert scores.state is not None
        assert scores.state.missing_series == 1
        assert scores.state.series_keys == trained.state.series_keys
        assert scores.state.scored_through == datetime(2026, 1, 11, tzinfo=UTC)
        assert scores.model_id == "model"

        # "gone" comes back. Its own newest scored bucket is still the one from the train step.
        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.run.return_value = MagicMock(
                results=[result("gone", datetime(2026, 1, 6, tzinfo=UTC), 7)]
            )
            returned = score_insight(
                insight,
                team,
                now=datetime(2026, 1, 13, 0, 30, tzinfo=UTC),
                after=trained.state.scored_through,
                split=SplitRun(state=scores.state, artifacts=trained.artifacts),
            )

        assert [point.bucket_start.day for point in returned.series[0].points] == [10, 11, 12]

    def test_a_score_pick_whose_state_no_longer_matches_the_insight_trains(self) -> None:
        stale = TrainedState(
            identity=StateIdentity(interval=IntervalType.DAY, detector_version="old", query_hash="old"),
            trained_at=datetime(2026, 1, 9, tzinfo=UTC),
            scored_through=datetime(2026, 1, 9, tzinfo=UTC),
            series_keys=("a",),
            artifact_key="anomaly_models/1/7/default-v1/old",
        )
        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.run.return_value = MagicMock(results=[])
            scores = score_insight(
                _insight([EventsNode(event="$pageview")]),
                Team(timezone="UTC"),
                now=datetime(2026, 1, 10, tzinfo=UTC),
                split=SplitRun(state=stale, artifacts={}),
            )

        assert scores.run == ScoringRun.TRAIN
        # The detector history and the backfill cap of a first visit, the same fetch as without the split.
        assert runner.call_args.kwargs["query"].dateRange.date_from == "-90d"

    @parameterized.expand([(interval.value, interval) for interval in DEFAULT_PROFILE.intervals])
    def test_a_train_step_scores_a_backfill_like_score_series_and_stores_the_newest_fit(
        self, _name: str, interval: IntervalType
    ) -> None:
        buckets = [datetime(2024, 1, 1, tzinfo=UTC)]
        while len(buckets) < 400:
            buckets.append(bucket_end(buckets[-1], interval))
        rng = np.random.default_rng(5)
        # The step size grows with the level, so one fit before the backfill goes stale over its buckets.
        steps = np.linspace(1, 40, len(buckets)) * (1 + rng.normal(0, 0.3, size=len(buckets)))
        values = list(1000 + np.cumsum(steps))
        result = {
            "order": 0,
            "label": "pageview",
            "breakdown_value": None,
            "days": [bucket.strftime("%Y-%m-%d %H:%M:%S") for bucket in buckets],
            "data": values,
        }
        now = bucket_end(buckets[-1], interval)
        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.run.return_value = MagicMock(results=[result])
            scores = score_insight(
                _insight([EventsNode(event="$pageview")], interval=interval),
                Team(timezone="UTC"),
                now=now,
                split=SplitRun(),
            )

        assert scores.run == ScoringRun.TRAIN and scores.artifacts is not None
        assert set(scores.artifacts) == {series.series_key for series in scores.series} != set()
        scoring = DEFAULT_PROFILE.intervals[interval]
        expected = score_series(values, buckets, scoring=scoring, interval=interval, now=now)
        points = scores.series[0].points
        assert len(points) == DEFAULT_LIMITS.max_backfill_buckets
        assert all(point.score is not None for point in points)
        assert [(point.bucket_start, point.flag) for point in points] == [
            (point.bucket_start, point.flag) for point in expected
        ]
        assert [point.score for point in points] == pytest.approx([point.score for point in expected])
        newest_window = np.array(values[len(values) - (history_buckets(scoring) - 1) :], dtype=float)
        assert scores.artifacts[scores.series[0].series_key] == get_detector(scoring.detector).fit(newest_window)


_IDENTITY = StateIdentity(interval=IntervalType.DAY, detector_version="v1", query_hash="q1")
_SCORED_THROUGH = datetime(2026, 1, 9, tzinfo=UTC)


def _state(**changes: Any) -> TrainedState:
    fields: dict[str, Any] = {
        "identity": _IDENTITY,
        "trained_at": datetime(2026, 1, 5, tzinfo=UTC),
        "scored_through": _SCORED_THROUGH,
        "series_keys": ("a", "b"),
        "artifact_key": "anomaly_models/1/7/default-v1/model",
        **changes,
    }
    return TrainedState(**fields)


class TestTrainDue(SimpleTestCase):
    @parameterized.expand(
        [
            ("fresh_state", _state(), TrainDue.NO),
            ("one_of_two_series_missing", _state(missing_series=1), TrainDue.NO),
            ("no_state", None, TrainDue.HARD),
            ("no_artifact", _state(artifact_key=""), TrainDue.HARD),
            (
                "query_changed",
                _state(identity=StateIdentity(interval=IntervalType.DAY, detector_version="v1", query_hash="q0")),
                TrainDue.HARD,
            ),
            (
                "detector_changed",
                _state(identity=StateIdentity(interval=IntervalType.DAY, detector_version="v0", query_hash="q1")),
                TrainDue.HARD,
            ),
            ("trained_too_long_ago", _state(trained_at=datetime(2026, 1, 2, tzinfo=UTC)), TrainDue.SOFT),
            ("past_the_model_age_ceiling", _state(trained_at=datetime(2025, 12, 13, tzinfo=UTC)), TrainDue.HARD),
            ("gap_over_the_backfill_cap", _state(scored_through=datetime(2025, 12, 1, tzinfo=UTC)), TrainDue.SOFT),
            ("most_series_missing", _state(missing_series=2), TrainDue.HARD),
        ]
    )
    def test_only_a_missing_or_untrusted_model_stops_score_steps(
        self, _name: str, state: TrainedState | None, expected: TrainDue
    ) -> None:
        assert (
            train_due(
                state,
                identity=_IDENTITY,
                now=datetime(2026, 1, 10, 1, tzinfo=UTC),
                timezone=ZoneInfo("UTC"),
                train_every=7,
                max_model_age=28,
                max_backfill=30,
            )
            == expected
        )

    @parameterized.expand([("kept_current", 23, TrainDue.NO), ("retrain_due", 24, TrainDue.SOFT)])
    def test_an_hourly_insight_kept_current_is_due_only_after_train_every(
        self, _name: str, hours_since_trained: int, expected: TrainDue
    ) -> None:
        identity = StateIdentity(interval=IntervalType.HOUR, detector_version="v1", query_hash="q1")
        now = datetime(2026, 1, 10, 12, 5, tzinfo=UTC)
        state = _state(
            identity=identity,
            trained_at=now - timedelta(hours=hours_since_trained),
            scored_through=datetime(2026, 1, 10, 10, tzinfo=UTC),
        )

        assert (
            train_due(
                state,
                identity=identity,
                now=now,
                timezone=ZoneInfo("UTC"),
                train_every=24,
                max_model_age=96,
                max_backfill=30,
            )
            == expected
        )


class TestMetricScoringQuery(SimpleTestCase):
    @parameterized.expand([("without_compare", None), ("with_saved_compare", CompareFilter(compare=True))])
    def test_metric_display_is_scored_as_a_line_without_the_previous_period(
        self, _name: str, compare_filter: CompareFilter | None
    ) -> None:
        insight = _insight(
            [EventsNode(event="$pageview"), EventsNode(event="signed_up")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.METRIC),
            compareFilter=compare_filter,
        )

        with patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner:
            runner.return_value.run.return_value = MagicMock(results=[])
            score_insight(insight, Team(timezone="UTC"), now=datetime(2026, 1, 10, tzinfo=UTC))

        query = runner.call_args.kwargs["query"]
        assert query.trendsFilter.display == ChartDisplayType.ACTIONS_LINE_GRAPH
        assert query.compareFilter is None
        assert query_cost(insight, MagicMock(spec=Team)) == 2


class TestFetchBuckets(SimpleTestCase):
    def test_unbounded_smoothing_is_not_scored(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], trendsFilter=TrendsFilter(smoothingIntervals=10_000_000)
        )

        with self.assertRaises(UnsupportedInsightError):
            fetch_buckets(query, DAY_SCORING, 1)


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
                "calendar_heatmap",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.CALENDAR_HEATMAP),
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


def _events(count: int) -> list[dict[str, Any]]:
    return [{"kind": "EventsNode", "event": f"event_{i}"} for i in range(count)]


class TestQueryCost(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_per_series", {"kind": "TrendsQuery", "series": _events(3)}, 3),
            ("wrapped", {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": _events(2)}}, 2),
            (
                "breakdown_and_formula_add_none",
                {
                    "kind": "TrendsQuery",
                    "series": _events(2),
                    "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
                    "trendsFilter": {"formulas": ["A/B", "A+B"]},
                },
                2,
            ),
            # The scoring query keeps every series, so the charge has no series cap.
            ("more_series_than_max_series", {"kind": "TrendsQuery", "series": _events(30)}, 30),
            (
                "one_per_cohort",
                {
                    "kind": "TrendsQuery",
                    "series": _events(2),
                    "breakdownFilter": {"breakdown": ["all", 1, 2], "breakdown_type": "cohort"},
                },
                6,
            ),
            # The scoring query drops the previous period.
            ("compare_adds_none", {"kind": "TrendsQuery", "series": _events(2), "compareFilter": {"compare": True}}, 2),
            ("not_scored", {"kind": "FunnelsQuery", "series": _events(4)}, 1),
            (
                "empty_series_with_breakdown",
                {
                    "kind": "TrendsQuery",
                    "series": [],
                    "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
                },
                1,
            ),
        ]
    )
    def test_a_pick_costs_the_queries_the_scoring_runner_sends(
        self, _name: str, query: dict[str, Any], expected: int
    ) -> None:
        assert query_cost(Insight(id=1, query=query), MagicMock(spec=Team)) == expected
