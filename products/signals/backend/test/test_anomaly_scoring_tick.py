from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import IntervalType

from posthog.models import Organization, Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.api import record_insight_view
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import DISABLED, AnomalyScoringConfig, parse_config
from products.signals.backend.anomaly_scores.emission import SCORER_DISTINCT_ID, score_events
from products.signals.backend.anomaly_scores.scoring import InsightScores, ScoredPoint, ScoredSeries
from products.signals.backend.anomaly_scores.queue import (
    WatchedInsight,
    eligible_teams,
    is_due,
    order_insights,
    scored_buckets,
    watched_insights,
)
from products.signals.backend.anomaly_scores.tick import plan_tick

NEW_YORK = ZoneInfo("America/New_York")
ORGANIZATION_ID = "4dc8564d-bd82-1065-2f40-97f7c50f67cf"


def _trends(**source: Any) -> dict[str, Any]:
    return {
        "kind": "InsightVizNode",
        "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], **source},
    }


def _scores(*series: ScoredSeries) -> InsightScores:
    return InsightScores(
        interval=IntervalType.DAY, profile="default-v1", detector="zscore", detector_version="v1", series=list(series)
    )


def _series(key: str, starts: list[datetime]) -> ScoredSeries:
    return ScoredSeries(
        series_key=key,
        label=key,
        breakdown_value=None,
        points=[ScoredPoint(bucket_start=start, value=1.0, score=0.5, flag=False, details={}) for start in starts],
    )


class TestTickConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", None),
            ("not_an_object", "enabled"),
            ("no_enabled", {"organization_ids": [ORGANIZATION_ID]}),
            ("enabled_not_bool", {"enabled": "true", "organization_ids": [ORGANIZATION_ID]}),
            ("disabled", {"enabled": False, "organization_ids": [ORGANIZATION_ID], "allow_team_ids": [2]}),
        ]
    )
    def test_a_missing_or_malformed_payload_does_no_work(self, _name: str, payload: Any) -> None:
        with (
            patch("products.signals.backend.anomaly_scores.config.read_flag_payload", return_value=payload),
            patch(
                "products.signals.backend.anomaly_scores.tick.select_insights", side_effect=AssertionError("selected")
            ),
        ):
            plan = plan_tick(None, datetime(2026, 10, 22, tzinfo=UTC))

        assert (plan.enabled, plan.picks) == (False, [])

    def test_invalid_fields_fall_back_and_limits_are_capped(self) -> None:
        config = parse_config(
            {
                "enabled": True,
                "organization_ids": [ORGANIZATION_ID, "not-a-uuid"],
                "allow_team_ids": [2, True, "3"],
                "intervals": ["minute", "week"],
                "max_insights_per_tick": 0,
                "limits": {"max_backfill_buckets": 100_000, "max_series": -1},
            }
        )

        assert config.organization_ids == (ORGANIZATION_ID,)
        assert config.allow_team_ids == (2,)
        assert config.intervals == (IntervalType.WEEK,)
        assert config.max_insights_per_tick == DISABLED.max_insights_per_tick
        assert (config.limits.max_backfill_buckets, config.limits.max_series) == (90, 20)


class TestTickSelection(SimpleTestCase):
    @parameterized.expand(
        [
            ("never_scored", IntervalType.DAY, UTC, None, datetime(2026, 10, 22, tzinfo=UTC), True),
            # The bucket after 20 October ends at midnight on the 22nd, plus a slot of up to an hour.
            (
                "next_day_ongoing",
                IntervalType.DAY,
                UTC,
                datetime(2026, 10, 20, tzinfo=UTC),
                datetime(2026, 10, 21, 23, tzinfo=UTC),
                False,
            ),
            (
                "next_day_complete",
                IntervalType.DAY,
                UTC,
                datetime(2026, 10, 20, tzinfo=UTC),
                datetime(2026, 10, 22, 1, 1, tzinfo=UTC),
                True,
            ),
            (
                "next_week_ongoing",
                IntervalType.WEEK,
                UTC,
                datetime(2026, 10, 5, tzinfo=UTC),
                datetime(2026, 10, 18, tzinfo=UTC),
                False,
            ),
            (
                "next_week_complete",
                IntervalType.WEEK,
                UTC,
                datetime(2026, 10, 5, tzinfo=UTC),
                datetime(2026, 10, 19, 1, 1, tzinfo=UTC),
                True,
            ),
        ]
    )
    def test_an_insight_is_due_once_the_bucket_after_its_newest_scored_one_completes(
        self,
        _name: str,
        interval: IntervalType,
        timezone: ZoneInfo,
        newest_bucket: datetime | None,
        now: datetime,
        due: bool,
    ) -> None:
        insight = WatchedInsight(team_id=1, insight_id=7, interval=interval)

        assert is_due(insight, newest_bucket, timezone, now) is due

    def test_never_scored_insights_come_first_then_the_stalest_round_robin_over_teams(self) -> None:
        insights = [
            WatchedInsight(team_id=team_id, insight_id=insight_id, interval=IntervalType.DAY)
            for team_id, insight_id in [(1, 1), (1, 2), (1, 3), (1, 4), (2, 5)]
        ]
        newest = {
            1: None,
            2: None,
            3: datetime(2026, 9, 1, tzinfo=UTC),
            4: datetime(2026, 10, 20, tzinfo=UTC),
            5: datetime(2026, 10, 19, tzinfo=UTC),
        }

        ordered = [insight.insight_id for insight in order_insights(insights, newest)]

        assert {ordered[0], ordered[2]} == {1, 2}
        assert ordered[1] == 5
        assert ordered[3:] == [3, 4]
        assert ordered == [insight.insight_id for insight in order_insights(list(reversed(insights)), newest)]


class TestScoreEvents(SimpleTestCase):
    def test_a_revisit_emits_every_bucket_after_the_newest_scored_one_of_each_series(self) -> None:
        starts = [datetime(2026, 10, day, tzinfo=NEW_YORK) for day in range(15, 20)]
        scores = _scores(_series("scored", starts), _series("new", starts))

        events = score_events(
            team_id=1,
            insight_id=7,
            scores=scores,
            scored_through={"scored": starts[2].astimezone(UTC)},
            scored_at=datetime(2026, 10, 22, tzinfo=UTC),
        )

        emitted = [
            (event["properties"]["$anomaly_series_key"], event["properties"]["$anomaly_bucket_start"])
            for event in events
        ]
        assert emitted == [("scored", start.isoformat()) for start in starts[3:]] + [
            ("new", start.isoformat()) for start in starts
        ]

    def test_the_event_carries_the_bucket_start_and_null_score_and_flag_during_warm_up(self) -> None:
        start = datetime(2026, 10, 19, tzinfo=NEW_YORK)
        series = ScoredSeries(
            series_key="series",
            label="Pageviews",
            breakdown_value=None,
            points=[
                ScoredPoint(bucket_start=start, value=3.0, score=None, flag=None, details={}),
                ScoredPoint(
                    bucket_start=start + timedelta(days=1), value=90.0, score=0.99, flag=True, details={"mean": 3.0}
                ),
            ],
        )

        def emit_at(scored_at: datetime) -> list[dict[str, Any]]:
            return score_events(team_id=1, insight_id=7, scores=_scores(series), scored_through={}, scored_at=scored_at)

        warm_up, flagged = emit_at(datetime(2026, 10, 22, tzinfo=UTC))

        assert warm_up["event"] == "$anomaly_score"
        assert warm_up["distinct_id"] == SCORER_DISTINCT_ID
        assert warm_up["timestamp"] == "2026-10-19T04:00:00+00:00"
        assert warm_up["options"] == {"process_person_profile": False}
        assert warm_up["properties"]["$anomaly_bucket_start"] == "2026-10-19T00:00:00-04:00"
        assert (warm_up["properties"]["$anomaly_score"], warm_up["properties"]["$anomaly_flag"]) == (None, None)
        assert (flagged["properties"]["$anomaly_score"], flagged["properties"]["$anomaly_flag"]) == (0.99, 1)
        # A resent bucket keeps its uuid, so ClickHouse replaces the earlier row instead of adding one.
        assert [event["event_uuid"] for event in emit_at(datetime(2026, 10, 23, tzinfo=UTC))] == [
            warm_up["event_uuid"],
            flagged["event_uuid"],
        ]


class TestEligibleTeams(BaseTest):
    @parameterized.expand(
        [
            ("every_team_of_the_organization", [], [], False, {"main", "second"}),
            ("allowlist", ["main"], [], False, {"main"}),
            ("skip_list", [], ["main"], False, {"second"}),
            ("quota_limited", [], [], True, {"main"}),
        ]
    )
    def test_only_allowed_teams_under_their_event_quota_are_scored(
        self, _name: str, allow: list[str], skip: list[str], second_limited: bool, expected: set[str]
    ) -> None:
        teams = {"main": self.team, "second": Team.objects.create(organization=self.organization, name="second")}
        other = Organization.objects.create(name="other")
        Team.objects.create(organization=other, name="other")
        config = AnomalyScoringConfig(
            enabled=True,
            organization_ids=(str(self.organization.id),),
            allow_team_ids=tuple(teams[name].id for name in allow),
            skip_team_ids=tuple(teams[name].id for name in skip),
        )
        limited = [teams["second"].api_token] if second_limited else []

        with patch(
            "products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=limited
        ):
            eligible = {team.id for team in eligible_teams(config)}

        assert eligible == {teams[name].id for name in expected}


class TestWatchedInsights(BaseTest):
    def test_only_watched_time_series_trends_with_a_scored_interval_are_eligible(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=query)
            for name, query in {
                "on_dashboard": _trends(interval="day"),
                "viewed": _trends(interval="week"),
                "default_interval": _trends(),
                "hourly": _trends(interval="hour"),
                "funnel": {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}},
                "bold_number": _trends(interval="day", trendsFilter={"display": "BoldNumber"}),
                "cumulative": _trends(interval="day", trendsFilter={"display": "ActionsLineGraphCumulative"}),
                "deleted_tile": _trends(interval="day"),
                "unwatched": _trends(interval="day"),
            }.items()
        }
        for name in ("on_dashboard", "default_interval", "hourly", "funnel", "bold_number", "cumulative"):
            DashboardTile.objects.create(dashboard=dashboard, insight=insights[name])
        DashboardTile.objects.create(dashboard=dashboard, insight=insights["deleted_tile"], deleted=True)
        record_insight_view(insight_id=insights["viewed"].id, team_id=self.team.id, user_id=self.user.id)

        watched = watched_insights(
            [self.team.id], (IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH), datetime.now(UTC)
        )

        names = {insight.id: name for name, insight in insights.items()}
        assert {(names[insight.insight_id], insight.interval) for insight in watched} == {
            ("on_dashboard", IntervalType.DAY),
            ("viewed", IntervalType.WEEK),
            ("default_interval", IntervalType.DAY),
        }


class TestScoredBuckets(ClickhouseTestMixin, BaseTest):
    def test_reads_the_newest_scored_bucket_of_each_series(self) -> None:
        def score(insight_id: int, series_key: str, bucket: datetime, source: str = "insight") -> None:
            _create_event(
                team=self.team,
                event="$anomaly_score",
                distinct_id=SCORER_DISTINCT_ID,
                timestamp=bucket,
                properties={
                    "$anomaly_insight_id": insight_id,
                    "$anomaly_series_key": series_key,
                    "$anomaly_source": source,
                },
            )

        score(7, "a", datetime(2026, 10, 18, tzinfo=UTC))
        score(7, "a", datetime(2026, 10, 20, tzinfo=UTC))
        score(7, "b", datetime(2026, 10, 19, tzinfo=UTC))
        score(8, "c", datetime(2026, 10, 21, tzinfo=UTC))
        score(9, "d", datetime(2026, 10, 21, tzinfo=UTC), source="default")
        score(10, "e", datetime(2026, 1, 1, tzinfo=UTC))

        state = scored_buckets(self.team, since=datetime(2026, 9, 1, tzinfo=UTC))

        assert state == {
            7: {"a": datetime(2026, 10, 20, tzinfo=UTC), "b": datetime(2026, 10, 19, tzinfo=UTC)},
            8: {"c": datetime(2026, 10, 21, tzinfo=UTC)},
        }
