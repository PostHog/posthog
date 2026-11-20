import json
import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import IntervalType

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.emission import SCORER_DISTINCT_ID
from products.signals.backend.anomaly_scores.read import ChartShare, FlaggedPoint, SeriesSummary, rank_series, rollup
from products.signals.backend.anomaly_scores.search import (
    MAX_INSIGHT_SERIES,
    SCORING_DISABLED_MESSAGE,
    SCORING_SOURCE_OFF_MESSAGE,
    SCORING_TURNED_OFF_MESSAGE,
    is_noisy,
)
from products.signals.backend.contracts import ALERT_SCOPE_SOURCE
from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig

NOW = datetime.datetime(2026, 10, 23, 12, tzinfo=datetime.UTC)


def _day(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, tzinfo=datetime.UTC)


def _summary(
    key: str,
    *,
    scored: int,
    flagged: int,
    last_flagged: datetime.datetime | None = None,
    interval: IntervalType = IntervalType.DAY,
    newest_bucket: datetime.datetime | None = None,
) -> SeriesSummary:
    newest_bucket = newest_bucket or _day(22)
    return SeriesSummary(
        insight_id=1,
        series_key=key,
        series_label=key,
        breakdown_value=None,
        interval=interval,
        detector="zscore",
        detector_version="v1",
        profile="default-v1",
        newest_bucket=newest_bucket,
        scored_buckets=scored,
        flagged_buckets=flagged,
        scored_through=newest_bucket,
        flagged_points=(FlaggedPoint(bucket_start=last_flagged, value=1.0, score=0.99),) if last_flagged else (),
    )


class TestAnomalyRanking(SimpleTestCase):
    @parameterized.expand(
        [
            ("rarely_flagged_beats_often_flagged", ("rare", 30, 1), ("noisy", 30, 10)),
            ("a_share_beats_too_few_chart_buckets", ("known", 30, 9), ("young", 9, 1)),
            ("a_share_beats_no_chart_share", ("known", 30, 9), ("missing", 0, 0)),
        ]
    )
    def test_unusual_order_puts_the_lowest_chart_share_first(
        self, _name: str, expected_first: tuple[str, int, int], other: tuple[str, int, int]
    ) -> None:
        series = [_summary(key, scored=10, flagged=1) for key, _, _ in (other, expected_first)]
        shares = {
            (1, key): ChartShare(scored_buckets=scored, flagged_buckets=flagged)
            for key, scored, flagged in (other, expected_first)
            if scored
        }

        ranked = rank_series(series, chart_shares=shares, importance={})

        assert [summary.series_key for summary in ranked] == [expected_first[0], other[0]]

    def test_unusual_order_puts_series_flagged_in_the_range_first(self) -> None:
        series = [_summary("quiet", scored=10, flagged=0), _summary("flagged", scored=10, flagged=1)]
        shares = {
            (1, "quiet"): ChartShare(scored_buckets=30, flagged_buckets=0),
            (1, "flagged"): ChartShare(scored_buckets=30, flagged_buckets=20),
        }

        ranked = rank_series(series, chart_shares=shares, importance={})

        assert [summary.series_key for summary in ranked] == ["flagged", "quiet"]

    @parameterized.expand(
        [("unusual", False, ["burst", "blip", "quiet"]), ("recent", True, ["blip", "burst", "quiet"])]
    )
    def test_ranks_by_the_newest_flag_only_when_recent_first(
        self, _name: str, recent_first: bool, expected: list[str]
    ) -> None:
        series = [
            _summary("quiet", scored=10, flagged=0),
            _summary("blip", scored=10, flagged=1, last_flagged=_day(22)),
            _summary("burst", scored=10, flagged=4, last_flagged=_day(15)),
        ]

        ranked = rank_series(series, chart_shares={}, importance={}, recent_first=recent_first)

        assert [summary.series_key for summary in ranked] == expected

    @parameterized.expand(
        [
            (
                "hourly_flag_hours_ago_beats_a_daily_flag_that_ended_earlier",
                [
                    _summary("daily_burst", scored=10, flagged=4, last_flagged=_day(22)),
                    _summary(
                        "hourly_blip",
                        scored=24,
                        flagged=1,
                        last_flagged=NOW - datetime.timedelta(hours=4),
                        interval=IntervalType.HOUR,
                        newest_bucket=NOW - datetime.timedelta(hours=1),
                    ),
                ],
                ["hourly_blip", "daily_burst"],
            ),
            (
                "compares_bucket_ends_not_starts",
                [
                    _summary(
                        "hourly_burst",
                        scored=24,
                        flagged=4,
                        last_flagged=_day(22) + datetime.timedelta(hours=22),
                        interval=IntervalType.HOUR,
                        newest_bucket=NOW - datetime.timedelta(hours=1),
                    ),
                    _summary("daily_blip", scored=10, flagged=1, last_flagged=_day(22)),
                ],
                ["daily_blip", "hourly_burst"],
            ),
            (
                "weekly_flag_that_ended_days_ago_sorts_below_flags_today",
                [
                    _summary(
                        "weekly",
                        scored=1,
                        flagged=1,
                        last_flagged=_day(12),
                        interval=IntervalType.WEEK,
                        newest_bucket=_day(12),
                    ),
                    _summary("daily", scored=10, flagged=1, last_flagged=_day(22)),
                    _summary(
                        "hourly",
                        scored=24,
                        flagged=1,
                        last_flagged=NOW - datetime.timedelta(hours=2),
                        interval=IntervalType.HOUR,
                        newest_bucket=NOW - datetime.timedelta(hours=1),
                    ),
                ],
                ["hourly", "daily", "weekly"],
            ),
            (
                "same_end_falls_back_to_flagged_buckets",
                [
                    _summary("daily", scored=10, flagged=1, last_flagged=_day(22)),
                    _summary(
                        "weekly",
                        scored=2,
                        flagged=2,
                        last_flagged=_day(16),
                        interval=IntervalType.WEEK,
                        newest_bucket=_day(16),
                    ),
                ],
                ["weekly", "daily"],
            ),
        ]
    )
    def test_recent_order_sorts_by_when_the_newest_flag_ended(
        self, _name: str, series: list[SeriesSummary], expected: list[str]
    ) -> None:
        ranked = rank_series(series, chart_shares={}, importance={}, recent_first=True)

        assert [summary.series_key for summary in ranked] == expected

    @parameterized.expand(
        [("unusual", False, ["three_of_ten", "one_of_one"]), ("rate", True, ["one_of_one", "three_of_ten"])]
    )
    def test_ranks_by_the_plain_rate_only_when_rate_first(
        self, _name: str, rate_first: bool, expected: list[str]
    ) -> None:
        series = [_summary("three_of_ten", scored=10, flagged=3), _summary("one_of_one", scored=1, flagged=1)]

        ranked = rank_series(series, chart_shares={}, importance={}, rate_first=rate_first)

        assert [summary.series_key for summary in ranked] == expected

    @parameterized.expand(
        [
            ("above_the_limit", ChartShare(scored_buckets=10, flagged_buckets=2), 0.1, True),
            ("at_the_limit", ChartShare(scored_buckets=10, flagged_buckets=1), 0.1, False),
            ("too_few_buckets_to_judge", ChartShare(scored_buckets=9, flagged_buckets=9), 0.1, False),
            ("no_scored_bucket_in_the_window", None, 0.1, False),
            ("filter_off", ChartShare(scored_buckets=10, flagged_buckets=10), 1.0, False),
        ]
    )
    def test_noise_filter_hides_only_a_high_share_over_enough_buckets(
        self, _name: str, chart_share: ChartShare | None, max_anomaly_rate: float, expected: bool
    ) -> None:
        assert is_noisy(chart_share, max_anomaly_rate) is expected

    def test_rollup_sums_buckets_instead_of_averaging_rates(self) -> None:
        insight = rollup(
            [_summary("a", scored=1, flagged=1), _summary("b", scored=9, flagged=1), _summary("c", scored=5, flagged=0)]
        )

        assert (insight.series_count, insight.flagged_series, insight.scored_buckets, insight.flagged_buckets) == (
            3,
            2,
            15,
            2,
        )
        assert insight.anomaly_rate == 2 / 15


@time_machine.travel(NOW, tick=False)
class TestAnomalySearchAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups", saved=True)
        self.source = SignalSourceConfig.objects.create(
            team=self.team, source_product=ALERT_SCOPE_SOURCE[0], source_type=ALERT_SCOPE_SOURCE[1], enabled=True
        )
        flag = patch("products.signals.backend.presentation.anomalies.feature_enabled_or_false", return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        payload = patch(
            "products.signals.backend.anomaly_scores.search.read_payload",
            return_value={"enabled": True, "organization_ids": [str(self.organization.id)]},
        )
        self.payload = payload.start()
        self.addCleanup(payload.stop)

    def _score(
        self,
        bucket: datetime.datetime,
        *,
        score: float | None,
        flag: int | None,
        scored_at: datetime.datetime = NOW,
        series_key: str = "signups",
        interval: str = "day",
        insight: Insight | None = None,
        team: Team | None = None,
        timestamp: datetime.datetime | None = None,
    ) -> None:
        _create_event(
            team=team or self.team,
            event="$anomaly_score",
            distinct_id=SCORER_DISTINCT_ID,
            timestamp=timestamp or bucket,
            properties={
                "$anomaly_score": score,
                "$anomaly_flag": flag,
                "$anomaly_value": 10.0,
                "$anomaly_bucket_start": bucket.isoformat(),
                "$anomaly_interval": interval,
                "$anomaly_series_key": series_key,
                "$anomaly_source": "insight",
                "$anomaly_insight_id": (insight or self.insight).id,
                "$anomaly_series_label": series_key.title(),
                "$anomaly_breakdown_value": None,
                "$anomaly_detector": "zscore",
                "$anomaly_detector_version": "v1",
                "$anomaly_profile": "default-v1",
                "$anomaly_scored_at": scored_at.isoformat(),
                "$anomaly_details": '{"z": 3.1}',
            },
        )

    def _score_history(self) -> None:
        # Oct 19 was scored twice: the rescore unflagged it. Oct 20 is warm-up, Oct 21 was never scored.
        self._score(_day(19), score=0.99, flag=1, scored_at=_day(20))
        self._score(_day(19), score=0.40, flag=0, scored_at=_day(21))
        self._score(_day(20), score=None, flag=None)
        self._score(_day(22), score=0.98, flag=1)
        self._score(_day(22), score=0.10, flag=0, series_key="logins")
        # Any member can capture a row like this. The scorer never writes a `second` interval.
        self._score(_day(22), score=0.99, flag=1, series_key="forged", interval="second")

    def _get(self, endpoint: str, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/anomalies/{endpoint}/", params)

    def _points(self, *series: tuple[Insight, str, str]) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/signals/anomalies/points/",
            {
                "series": [
                    {"insight_id": insight.id, "series_key": series_key, "interval": interval}
                    for insight, series_key, interval in series
                ]
            },
            format="json",
        )

    def test_search_counts_the_latest_result_of_each_scored_bucket(self) -> None:
        self._score_history()

        response = self._get("search", date_from="2026-10-19")

        assert response.status_code == 200, response.json()
        body = response.json()
        assert (body["scoring_enabled"], body["insights_scored_in_range"], body["message"]) == (True, 1, None)
        assert len(body["series"]) == 1
        row = body["series"][0]
        assert {key: row[key] for key in ("series_key", "scored_buckets", "flagged_buckets", "expected_buckets")} == {
            "series_key": "signups",
            "scored_buckets": 2,
            "flagged_buckets": 1,
            "expected_buckets": 4,
        }
        assert (row["anomaly_rate"], row["coverage"]) == (0.5, 0.5)
        assert row["last_flagged_bucket"] == row["first_flagged_bucket"] == "2026-10-22T00:00:00+00:00"
        assert row["flagged_points"] == [{"bucket_start": "2026-10-22T00:00:00+00:00", "value": 10.0, "score": 0.98}]
        assert "points" not in row

    @parameterized.expand(
        [
            ("every_scored_bucket", 400, ["2026-10-10", "2026-10-19", "2026-10-22"]),
            ("capped_to_the_newest", 1, ["2026-10-22"]),
        ]
    )
    def test_search_includes_the_scored_points_of_the_series_on_the_page(
        self, _name: str, cap: int, expected_days: list[str]
    ) -> None:
        self._score_history()
        # Before the range but inside the 14-day daily chart window, then before the chart window.
        self._score(_day(10), score=0.20, flag=0)
        self._score(_day(9), score=0.20, flag=0)

        with patch("products.signals.backend.anomaly_scores.read.MAX_SERIES_POINTS", cap):
            body = self._get("search", date_from="2026-10-19", include_points=True).json()

        [row] = body["series"]
        assert (row["scored_buckets"], row["flagged_buckets"]) == (2, 1)
        # The warm-up bucket on Oct 20 and the unscored Oct 21 have no point. The rescore of Oct 19 wins.
        assert [(point["bucket_start"][:10], point["flag"]) for point in row["points"]] == [
            (day, day == "2026-10-22") for day in expected_days
        ]

    def test_search_returns_the_hourly_chart_window_of_every_series_on_the_page(self) -> None:
        hours = [NOW - datetime.timedelta(hours=hour) for hour in range(1, 201)]
        for series_key in ("signups", "logins", "upgrades"):
            for hour in hours:
                self._score(hour, score=0.99, flag=1, series_key=series_key, interval="hour")

        body = self._get("search", date_from="-3d", interval="hour", include_points=True, max_anomaly_rate=1).json()

        assert {row["series_key"]: (row["scored_buckets"], len(row["points"])) for row in body["series"]} == {
            "signups": (72, 7 * 24),
            "logins": (72, 7 * 24),
            "upgrades": (72, 7 * 24),
        }

    def test_points_reads_the_chart_window_of_each_requested_series_the_user_can_read(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_insight = Insight.objects.create(team=other_team, name="Other", saved=True)
        self._score(_day(22), score=0.98, flag=1)
        self._score(_day(10), score=0.20, flag=0)
        self._score(NOW - datetime.timedelta(hours=1), score=0.97, flag=1, series_key="logins", interval="hour")
        # Inside the daily window that the scan covers, but before the 7-day hourly window.
        self._score(NOW - datetime.timedelta(days=10), score=0.10, flag=0, series_key="logins", interval="hour")
        self._score(_day(22), score=0.98, flag=1, insight=other_insight, team=other_team)

        response = self._points(
            (self.insight, "signups", "day"), (self.insight, "logins", "hour"), (other_insight, "signups", "day")
        )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["date_to"] == "2026-10-23T12:00:00+00:00"
        assert [
            (row["series_key"], row["date_from"], [(point["bucket_start"], point["flag"]) for point in row["points"]])
            for row in body["series"]
        ] == [
            (
                "signups",
                "2026-10-09T12:00:00+00:00",
                [("2026-10-10T00:00:00+00:00", False), ("2026-10-22T00:00:00+00:00", True)],
            ),
            ("logins", "2026-10-16T12:00:00+00:00", [("2026-10-23T11:00:00+00:00", True)]),
        ]

    @parameterized.expand(
        [
            ("default_limit", {}, ["quiet", "sparse"], 1, None),
            ("filter_off", {"max_anomaly_rate": 1}, ["noisy", "quiet", "sparse"], 0, None),
            ("default_limit_by_insight", {"group_by": "insight"}, ["quiet", "sparse"], 1, None),
            # Over these 3 days both daily series flag 1 bucket in 3. Over the chart window only one is noisy.
            ("measured_over_the_chart_window", {"date_from": "2026-10-20"}, ["quiet", "sparse"], 1, None),
            (
                "every_flagged_series_hidden",
                {"max_anomaly_rate": 0.05, "interval": "day"},
                [],
                2,
                "The noise filter hid all 2 matching series",
            ),
        ]
    )
    def test_search_hides_series_above_the_anomaly_rate_limit(
        self, _name: str, params: dict[str, Any], expected: list[str], hidden: int, message: str | None
    ) -> None:
        flagged_days = {"noisy": {13, 16, 19, 22}, "quiet": {22}}
        for series_key, days in flagged_days.items():
            for day in range(11, 23):
                self._score(_day(day), score=0.5, flag=int(day in days), series_key=series_key)
        # 2 flags in 5 buckets is too few for the filter to judge.
        for hours_ago in range(1, 6):
            hour = NOW - datetime.timedelta(hours=hours_ago)
            self._score(hour, score=0.5, flag=int(hours_ago <= 2), series_key="sparse", interval="hour")

        body = self._get("search", **{"date_from": "2026-10-11", **params}).json()

        rows = body["series"] or [series for row in body["insights"] for series in row["top_series"]]
        assert sorted(row["series_key"] for row in rows) == expected
        assert body["hidden_series"] == hidden
        assert (body["message"] or "").startswith(message or "")
        assert body["max_anomaly_rate"] == params.get("max_anomaly_rate", 0.1)

    def test_search_links_the_insight_with_context_before_the_flags(self) -> None:
        for day in (20, 22):
            self._score(_day(day), score=0.99, flag=1, series_key="signups")

        row = self._get("search", date_from="2026-10-15").json()["series"][0]

        override = json.loads(parse_qs(urlparse(row["insight_url"]).query)["filters_override"][0])
        assert override == {"date_from": "2026-09-26T00:00:00+00:00", "date_to": "2026-10-26T00:00:00+00:00"}

    def test_search_names_the_live_dashboards_of_each_insight(self) -> None:
        other = Insight.objects.create(team=self.team, name="Checkout", saved=True)
        main = Dashboard.objects.create(team=self.team, name="Main")
        removed = Dashboard.objects.create(team=self.team, name="Removed", deleted=True)
        for dashboard in (main, removed):
            DashboardTile.objects.create(dashboard=dashboard, insight=self.insight)
        self._score(_day(22), score=0.99, flag=1, series_key="signups")
        self._score(_day(22), score=0.99, flag=1, series_key="checkout", insight=other)

        body = self._get("search", date_from="2026-10-15").json()

        assert {row["series_key"]: row["dashboards"] for row in body["series"]} == {
            "signups": [{"id": main.id, "name": "Main"}],
            "checkout": [],
        }

    @parameterized.expand(
        [
            ("unusual", "unusual", ["blip", "steady", "burst"]),
            ("recent", "recent", ["blip", "steady", "burst"]),
            ("rate", "rate", ["burst", "steady", "blip"]),
        ]
    )
    def test_search_pages_through_rows_in_the_requested_order(
        self, _name: str, order: str, expected: list[str]
    ) -> None:
        # Before the range but inside the daily chart window, burst also flagged often, so it sorts last as unusual.
        flagged_days = {"burst": {1, 2, 3, 4, 5, 6, 7, 15, 16, 17}, "steady": {19, 20}, "blip": {22}}
        for series_key, days in flagged_days.items():
            for day in range(1, 23):
                self._score(_day(day), score=0.5, flag=int(day in days), series_key=series_key)

        pages = [
            self._get("search", date_from="2026-10-15", order=order, limit=2, offset=offset, max_anomaly_rate=1).json()
            for offset in (0, 2)
        ]

        assert [row["series_key"] for page in pages for row in page["series"]] == expected
        assert [(page["order"], page["has_more"], page["series_capped"], page["message"]) for page in pages] == [
            (order, True, False, None),
            (order, False, False, None),
        ]

    @parameterized.expand(
        [
            ("flagged_only_reads_flagged_series_first", 1, {}, 1, False),
            ("every_series_counts_against_the_cap", 1, {"only_flagged": False}, 1, True),
            ("flagged_series_alone_pass_the_cap", 2, {}, 1, True),
            ("insight_rollups_need_every_series", 1, {"group_by": "insight"}, 1, True),
        ]
    )
    def test_search_reports_when_the_series_cap_drops_series_it_needs(
        self, _name: str, flagged: int, params: dict[str, Any], expected_rows: int, expected_capped: bool
    ) -> None:
        for index in range(flagged):
            self._score(_day(22), score=0.99, flag=1, series_key=f"flagged_{index}")
        for index in range(30):
            self._score(_day(22), score=0.10, flag=0, series_key=f"quiet_{index}")

        with patch("products.signals.backend.anomaly_scores.read.MAX_SERIES", 1):
            body = self._get("search", date_from="2026-10-19", **params).json()

        rows = body["series"] + [row for insight in body["insights"] for row in insight["top_series"]]
        assert [row["series_key"].startswith("flagged_") for row in rows] == [True] * expected_rows
        assert (body["has_more"], body["series_capped"], body["truncated"]) == (
            False,
            expected_capped,
            expected_capped,
        )

    def test_search_recent_order_mixes_intervals_on_the_first_page(self) -> None:
        for hours_ago in range(1, 25):
            hour = NOW - datetime.timedelta(hours=hours_ago)
            self._score(hour, score=0.5, flag=int(hours_ago == 4), series_key="hourly", interval="hour")
        for series_key, days in {"daily": {21, 22}, "older": {19}}.items():
            for day in range(15, 23):
                self._score(_day(day), score=0.5, flag=int(day in days), series_key=series_key)
        self._score(_day(15), score=0.5, flag=1, series_key="weekly", interval="week")

        pages = [
            self._get("search", date_from="2026-10-15", order="recent", limit=2, offset=offset).json()
            for offset in (0, 2)
        ]

        assert [[(row["series_key"], row["interval"]) for row in page["series"]] for page in pages] == [
            [("hourly", "hour"), ("daily", "day")],
            [("weekly", "week"), ("older", "day")],
        ]

    @parameterized.expand(
        [
            ("saved_name_ignoring_case", "SIGNUP", 1_000, ["signups"]),
            ("generated_name_only_without_a_saved_name", "pageview", 1_000, ["unnamed"]),
            ("filtered_after_the_read_when_many_insights_match", "pageview", 0, ["unnamed"]),
        ]
    )
    def test_search_keeps_insights_whose_name_matches(
        self, _name: str, search: str, max_scoped: int, expected: list[str]
    ) -> None:
        named = Insight.objects.create(team=self.team, name="Checkout", derived_name="Pageviews by browser", saved=True)
        unnamed = Insight.objects.create(team=self.team, name=None, derived_name="Pageviews", saved=True)
        for series_key, insight in (("signups", self.insight), ("checkout", named), ("unnamed", unnamed)):
            self._score(_day(22), score=0.99, flag=1, series_key=series_key, insight=insight)

        with patch("products.signals.backend.anomaly_scores.search.MAX_SCOPED_INSIGHTS", max_scoped):
            body = self._get("search", date_from="2026-10-19", search=search).json()

        assert [row["series_key"] for row in body["series"]] == expected

    @parameterized.expand(
        [
            ("too_few_scored_days", range(18, 23), False, (5, False)),
            ("ready_even_when_the_range_is_shorter", range(9, 23), False, (14, True)),
            ("ready_when_scoring_is_off", range(9, 23), True, (14, True)),
        ]
    )
    def test_search_reports_scored_history_over_a_fixed_window(
        self, _name: str, days: range, scoring_off: bool, expected: tuple[int, bool]
    ) -> None:
        for day in days:
            self._score(_day(day), score=0.1, flag=0)
        if scoring_off:
            self.payload.return_value = {"enabled": True, "organization_ids": []}

        body = self._get("search", date_from="2026-10-21").json()

        assert (body["scored_days"], body["scored_history_ready"]) == expected

    def test_scored_days_skip_warmup_hourly_and_old_buckets(self) -> None:
        for day in range(10, 23):
            self._score(_day(day), score=0.1, flag=0, series_key="a")
            self._score(_day(day), score=0.2, flag=0, series_key="b")
        self._score(_day(9), score=None, flag=None)
        self._score(_day(8), score=0.1, flag=0, interval="hour")
        self._score(NOW - datetime.timedelta(days=29), score=0.1, flag=0)

        body = self._get("search").json()

        assert (body["scored_days"], body["scored_history_ready"]) == (13, False)

    def test_search_reuses_the_cached_scored_days_of_the_team(self) -> None:
        for day in range(18, 23):
            self._score(_day(day), score=0.99, flag=1)
        assert self._get("search", date_from="2026-10-19").json()["scored_days"] == 5
        for day in range(9, 18):
            self._score(_day(day), score=0.1, flag=0)

        with patch(
            "products.signals.backend.anomaly_scores.read.execute_hogql_query", wraps=execute_hogql_query
        ) as query:
            body = self._get("search", date_from="2026-10-19", max_anomaly_rate=1).json()

        assert (len(body["series"]), body["scored_days"], body["scored_history_ready"]) == (1, 5, False)
        assert "AnomalyScoresScoredDays" not in [call.kwargs["query_type"] for call in query.call_args_list]

    @parameterized.expand(
        [
            ("search_outside_the_payload", "search", "payload", SCORING_DISABLED_MESSAGE),
            ("insight_outside_the_payload", "insight", "payload", SCORING_DISABLED_MESSAGE),
            ("search_with_the_source_off", "search", "source", SCORING_SOURCE_OFF_MESSAGE),
            ("insight_with_the_source_off", "insight", "source", SCORING_SOURCE_OFF_MESSAGE),
            ("search_turned_off_in_settings", "search", "settings", SCORING_TURNED_OFF_MESSAGE),
            ("insight_turned_off_in_settings", "insight", "settings", SCORING_TURNED_OFF_MESSAGE),
        ]
    )
    def test_explains_an_empty_result_for_a_team_that_is_not_scored(
        self, _name: str, endpoint: str, off_by: str, message: str
    ) -> None:
        if off_by == "payload":
            self.payload.return_value = {"enabled": True, "organization_ids": []}
        elif off_by == "source":
            self.source.enabled = False
            self.source.save()
        else:
            SignalTeamConfig.objects.create(team=self.team, anomaly_scoring_enabled=False)

        body = self._get(endpoint, insight_id=self.insight.id).json()

        assert (body["scoring_enabled"], body["message"]) == (False, message)

    def test_insight_returns_every_bucket_of_each_series_oldest_first(self) -> None:
        self._score_history()

        body = self._get("insight", insight_id=self.insight.id, date_from="2026-10-19").json()

        assert (body["series_count"], body["flagged_series"], body["scored_buckets"], body["flagged_buckets"]) == (
            2,
            1,
            3,
            1,
        )
        series = {row["series_key"]: row for row in body["series"]}
        assert [row["series_key"] for row in body["series"]] == ["signups", "logins"]
        assert [
            (bucket["bucket_start"][:10], bucket["scored"], bucket["score"], bucket["flag"])
            for bucket in series["signups"]["buckets"]
        ] == [
            ("2026-10-19", True, 0.40, False),
            ("2026-10-20", False, None, None),
            ("2026-10-21", False, None, None),
            ("2026-10-22", True, 0.98, True),
        ]
        assert series["signups"]["buckets"][-1]["details"] == {"z": 3.1}

    def test_insight_keys_buckets_on_the_declared_start_not_the_event_timestamp(self) -> None:
        ms = datetime.timedelta(milliseconds=1)
        self._score(_day(19), score=0.99, flag=1, scored_at=_day(20), timestamp=_day(19) - 5 * ms)
        self._score(_day(19), score=0.40, flag=0, scored_at=_day(21), timestamp=_day(19) + 7 * ms)
        self._score(_day(20), score=0.30, flag=0, timestamp=_day(20) + 41 * ms)
        self._score(_day(22), score=0.98, flag=1, timestamp=_day(22) + 4 * ms)

        body = self._get("insight", insight_id=self.insight.id, date_from="2026-10-19").json()

        [series] = body["series"]
        assert (series["scored_buckets"], series["expected_buckets"]) == (3, 4)
        assert [(bucket["bucket_start"], bucket["scored"], bucket["score"]) for bucket in series["buckets"]] == [
            ("2026-10-19T00:00:00+00:00", True, 0.40),
            ("2026-10-20T00:00:00+00:00", True, 0.30),
            ("2026-10-21T00:00:00+00:00", False, None),
            ("2026-10-22T00:00:00+00:00", True, 0.98),
        ]

    def test_insight_narrows_to_one_series_and_shows_warmup_on_request(self) -> None:
        self._score_history()

        body = self._get(
            "insight", insight_id=self.insight.id, date_from="2026-10-19", series_key="signups", include_warmup=True
        ).json()

        assert [row["series_key"] for row in body["series"]] == ["signups"]
        warmup = body["series"][0]["buckets"][1]
        assert (warmup["bucket_start"][:10], warmup["scored"], warmup["score"], warmup["value"]) == (
            "2026-10-20",
            True,
            None,
            10.0,
        )

    def test_insight_caps_series_at_the_scorer_maximum(self) -> None:
        for index in range(MAX_INSIGHT_SERIES + 1):
            self._score(_day(22), score=0.5, flag=0, series_key=f"series_{index}")

        body = self._get("insight", insight_id=self.insight.id, date_from="2026-10-19").json()

        assert (len(body["series"]), body["series_count"], body["truncated"]) == (
            MAX_INSIGHT_SERIES,
            MAX_INSIGHT_SERIES + 1,
            True,
        )

    def test_insight_returns_404_for_an_insight_the_user_cannot_read(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_insight = Insight.objects.create(team=other_team, name="Other", saved=True)
        self._score(_day(22), score=0.98, flag=1, insight=other_insight)

        assert self._get("insight", insight_id=other_insight.id).status_code == 404
        assert self._get("search", date_from="2026-10-19").json()["series"] == []

    @parameterized.expand([("search",), ("insight",), ("points",)])
    def test_returns_404_when_the_flag_is_off(self, endpoint: str) -> None:
        self.flag.return_value = False

        response = (
            self._points((self.insight, "signups", "day"))
            if endpoint == "points"
            else self._get(endpoint, insight_id=self.insight.id)
        )
        assert response.status_code == 404
