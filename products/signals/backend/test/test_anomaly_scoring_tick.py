import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import IntervalType

from posthog.hogql.errors import QueryError, ResolutionError, TableAccessDeniedError

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models import Organization, Team, User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.api import record_insight_view
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import DISABLED, AnomalyScoringConfig, parse_config
from products.signals.backend.anomaly_scores.emission import SCORER_DISTINCT_ID, score_events
from products.signals.backend.anomaly_scores.queue import (
    SKIP_COOLDOWN,
    InsightPick,
    QueryBudget,
    WatchedInsight,
    _cooldown_key,
    _fleet_budget_key,
    _project_budget_key,
    eligible_teams,
    is_due,
    remaining_budget,
    reserve_queries,
    scored_buckets,
    select_insights,
    watched_insights,
    within_budget,
)
from products.signals.backend.anomaly_scores.scoring import (
    InsightScores,
    ScoredPoint,
    ScoredSeries,
    UnsupportedInsightError,
)
from products.signals.backend.anomaly_scores.selection import SelectionConfig, Weighting
from products.signals.backend.anomaly_scores.tick import (
    AnomalyScoringTickInput,
    AnomalyScoringTickPlan,
    AnomalyScoringTickResult,
    AnomalyScoringTickWorkflow,
    ScoreInsightInput,
    ScoreInsightResult,
    plan_tick,
    run_insight,
)

NEW_YORK = ZoneInfo("America/New_York")
ORGANIZATION_ID = "4dc8564d-bd82-1065-2f40-97f7c50f67cf"
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


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

    @parameterized.expand(
        [
            ("max_insights_per_tick", 51, 50),
            ("max_concurrency", 100, 8),
            ("max_queries_per_hour", 1_000_000, 2000),
            ("max_queries_per_project_per_hour", 501, 500),
        ]
    )
    def test_tick_levers_above_their_maximum_parse_to_the_maximum(self, field: str, value: int, expected: int) -> None:
        config = parse_config({"enabled": True, "organization_ids": [ORGANIZATION_ID], field: value})

        assert getattr(config, field) == expected


class TestQueryBudget(SimpleTestCase):
    @parameterized.expand(
        [
            # The second insight does not fit the 2 queries left, and the cheaper third one does.
            (
                "project_budget_skips_to_cheaper",
                {1: 1, 2: 1, 3: 1},
                QueryBudget(fleet=100, projects={1: 5}),
                10,
                [1, 3],
                1,
                0,
            ),
            (
                "fleet_budget_spans_projects",
                {1: 1, 2: 2, 3: 3},
                QueryBudget(fleet=4, projects={1: 30, 2: 30, 3: 30}),
                10,
                [1],
                2,
                0,
            ),
            ("project_spent", {1: 1, 2: 2, 3: 2}, QueryBudget(fleet=100, projects={1: 30, 2: 0}), 10, [1], 2, 0),
            ("tick_cap", {1: 1, 2: 1, 3: 1}, QueryBudget(fleet=100, projects={1: 30}), 1, [1], 0, 0),
            # Another tick reserved the queries after the snapshot.
            ("reservation_fails", {1: 1, 2: 1, 3: 1}, QueryBudget(fleet=100, projects={1: 30}), 10, [2, 3], 1, 1),
        ]
    )
    def test_the_walk_skips_picks_over_budget_and_continues(
        self,
        _name: str,
        team_ids: dict[int, int],
        budget: QueryBudget,
        limit: int,
        expected: list[int],
        skipped: int,
        refused_reservations: int,
    ) -> None:
        costs = {1: 3, 2: 3, 3: 2}
        calls: list[int] = []

        def reserve(team_id: int, cost: int) -> bool:
            calls.append(cost)
            return len(calls) > refused_reservations

        picked, skipped_count = within_budget(
            [1, 2, 3], team_ids, budget, limit, lambda ids: {i: costs[i] for i in ids}, reserve
        )

        assert (list(picked), skipped_count) == (expected, skipped)
        assert picked == {insight_id: costs[insight_id] for insight_id in expected}

    @parameterized.expand(
        [
            ("fleet_spent", QueryBudget(fleet=0, projects={1: 30, 2: 30}), []),
            ("one_project_spent", QueryBudget(fleet=100, projects={1: 0, 2: 30}), [[2, 4]]),
        ]
    )
    def test_costs_load_only_for_insights_a_budget_can_still_fit(
        self, _name: str, budget: QueryBudget, loaded: list[list[int]]
    ) -> None:
        batches: list[list[int]] = []

        def costs_for(insight_ids: list[int]) -> dict[int, int]:
            batches.append(insight_ids)
            return dict.fromkeys(insight_ids, 1)

        within_budget([1, 2, 3, 4], {1: 1, 2: 2, 3: 1, 4: 2}, budget, 10, costs_for, lambda _team, _cost: True)

        assert batches == loaded

    def test_a_reservation_takes_both_budgets_or_neither_and_resets_each_hour(self) -> None:
        config = AnomalyScoringConfig(enabled=True, max_queries_per_hour=10, max_queries_per_project_per_hour=6)
        next_hour = NOW + timedelta(hours=1)
        for now in (NOW, next_hour):
            cache.delete_many([_fleet_budget_key(now), _project_budget_key(1, now), _project_budget_key(2, now)])

        reserved = [
            reserve_queries(config, team_id, queries, NOW + timedelta(minutes=minute))
            for team_id, queries, minute in [(1, 3, 0), (1, 3, 10), (1, 1, 20), (2, 4, 30), (2, 1, 40)]
        ]

        assert reserved == [True, True, False, True, False]
        assert remaining_budget(config, [1, 2], NOW) == QueryBudget(fleet=0, projects={1: 0, 2: 2})
        assert remaining_budget(config, [1, 2], next_hour) == QueryBudget(fleet=10, projects={1: 6, 2: 6})


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

    def test_a_bucket_repeated_at_a_dst_fall_back_is_emitted_once(self) -> None:
        # Trends returns the 01:00 bucket twice on the fall-back night, and both parse to the same instant.
        starts = [datetime(2026, 11, 1, 0, tzinfo=NEW_YORK), datetime(2026, 11, 1, 1, tzinfo=NEW_YORK)]
        starts.append(starts[-1])

        events = score_events(
            team_id=1,
            insight_id=7,
            scores=_scores(_series("hourly", starts)),
            scored_through={},
            scored_at=datetime(2026, 11, 2, tzinfo=UTC),
        )

        assert [event["properties"]["$anomaly_bucket_start"] for event in events] == [
            start.isoformat() for start in starts[:2]
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


class TestRunInsight(SimpleTestCase):
    def _run(self, error: Exception) -> tuple[str, list[Any], MagicMock]:
        tick = "products.signals.backend.anomaly_scores.tick"
        client = MagicMock()
        with (
            patch(
                f"{tick}.insights_including_soft_deleted_for_team",
                return_value=[Insight(id=7, saved=True, deleted=False)],
            ),
            patch(f"{tick}.Team"),
            patch(f"{tick}.score_insight", side_effect=error),
            patch(f"{tick}.mark_attempted") as mark_attempted,
            patch("products.signals.backend.anomaly_scores.metrics.posthoganalytics.default_client", client),
        ):
            pick = InsightPick(team_id=1, insight_id=7, scored_through={}, interval=IntervalType.DAY)
            try:
                status = run_insight(ScoreInsightInput(pick=pick), NOW).status
            except Exception:
                status = "raised"
        cooldowns = [call.args[1] for call in mark_attempted.call_args_list]
        return status, cooldowns, client.metrics

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut(), "too_expensive"),
            ("access_denied", TableAccessDeniedError("no access"), "access_denied"),
            ("unknown_table", QueryError("Unknown table `deleted_table`."), "broken_query"),
            ("unsupported", UnsupportedInsightError("not trends"), "unsupported"),
        ]
    )
    def test_a_known_failure_returns_its_status_and_waits_a_day(
        self, _name: str, error: Exception, expected: str
    ) -> None:
        status, cooldowns, metrics = self._run(error)

        assert status == expected
        assert cooldowns[-1] == SKIP_COOLDOWN
        metrics.count.assert_any_call(
            "anomaly_scoring.picks", 1, attributes={"status": expected, "interval": IntervalType.DAY.value}
        )

    def test_a_full_cluster_returns_at_capacity_and_waits_an_hour(self) -> None:
        status, cooldowns, _metrics = self._run(ClickHouseAtCapacity())

        assert status == "at_capacity"
        assert SKIP_COOLDOWN not in cooldowns

    @parameterized.expand(
        [
            ("cluster_memory", ClickHouseClusterMemoryLimitExceeded()),
            ("internal_resolver", ResolutionError("Type already resolved for Field (FieldType). Can't run again.")),
            ("unknown", RuntimeError("boom")),
        ]
    )
    def test_any_other_failure_raises_and_waits_an_hour(self, _name: str, error: Exception) -> None:
        status, cooldowns, _metrics = self._run(error)

        assert status == "raised"
        assert SKIP_COOLDOWN not in cooldowns


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

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=limited):
            eligible = {team.id for team in eligible_teams(config)}

        assert eligible == {teams[name].id for name in expected}


class TestWatchedInsights(BaseTest):
    @time_machine.travel(NOW, tick=False)
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

        watched = watched_insights([self.team.id], (IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH), NOW)

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
        # Any member can capture these: one names an insight of another team, one a bucket in the future.
        score(11, "f", datetime(2026, 10, 21, tzinfo=UTC))
        score(8, "c", datetime(2027, 1, 1, tzinfo=UTC))

        state = scored_buckets(
            self.team,
            insight_ids={7, 8, 9, 10},
            since=datetime(2026, 9, 1, tzinfo=UTC),
            now=datetime(2026, 10, 22, tzinfo=UTC),
        )

        assert state == {
            7: {"a": datetime(2026, 10, 20, tzinfo=UTC), "b": datetime(2026, 10, 19, tzinfo=UTC)},
            8: {"c": datetime(2026, 10, 21, tzinfo=UTC)},
        }

    @time_machine.travel(NOW, tick=False)
    def test_select_insights_picks_due_insights_never_scored_first(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=_trends(interval="day"))
            for name in ("never_scored", "stale", "fresh")
        }
        for insight in insights.values():
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            cache.delete(_cooldown_key(insight.id))
        cache.delete_many([_fleet_budget_key(NOW), _project_budget_key(self.team.id, NOW)])
        today = NOW.replace(hour=0)
        for name, bucket in (("stale", today - timedelta(days=3)), ("fresh", today - timedelta(days=1))):
            _create_event(
                team=self.team,
                event="$anomaly_score",
                distinct_id=SCORER_DISTINCT_ID,
                timestamp=bucket,
                properties={
                    "$anomaly_insight_id": insights[name].id,
                    "$anomaly_series_key": name,
                    "$anomaly_source": "insight",
                },
            )
        config = AnomalyScoringConfig(
            enabled=True, organization_ids=(str(self.organization.id),), allow_team_ids=(self.team.id,)
        )

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            selection = select_insights(config, SelectionConfig(weighting=Weighting.UNIFORM), NOW, limit=10)

        assert [pick.insight_id for pick in selection.picks] == [insights["never_scored"].id, insights["stale"].id]
        assert selection.picks[1].scored_through == {"stale": today - timedelta(days=3)}

    @time_machine.travel(NOW, tick=False)
    def test_select_insights_lets_each_project_pick_before_any_project_picks_twice(self) -> None:
        small_team = Team.objects.create(organization=self.organization, name="Small")
        viewers = [
            User.objects.create_and_join(self.organization, f"viewer{index}@example.com", "password")
            for index in range(5)
        ]
        large_insights = []
        for index in range(3):
            insight = Insight.objects.create(team=self.team, name=f"large_{index}", query=_trends(interval="day"))
            for viewer in viewers:
                record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=viewer.id)
            large_insights.append(insight)
        small_insight = Insight.objects.create(team=small_team, name="small", query=_trends(interval="day"))
        small_dashboard = Dashboard.objects.create(team=small_team, name="Main")
        DashboardTile.objects.create(dashboard=small_dashboard, insight=small_insight)
        for insight in [*large_insights, small_insight]:
            cache.delete(_cooldown_key(insight.id))
        config = AnomalyScoringConfig(
            enabled=True,
            organization_ids=(str(self.organization.id),),
            allow_team_ids=(self.team.id, small_team.id),
        )

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            selection = select_insights(config, SelectionConfig(weighting=Weighting.WEIGHTED), NOW, limit=2)

        assert [pick.team_id for pick in selection.picks] == [self.team.id, small_team.id]
        assert selection.picks[0].insight_id in {insight.id for insight in large_insights}
        assert selection.picks[1].insight_id == small_insight.id
        assert selection.candidates == 4


async def _run_tick(
    plan: AnomalyScoringTickPlan, statuses: dict[int, str]
) -> tuple[AnomalyScoringTickResult, list[int]]:
    started: list[int] = []

    @activity.defn(name="plan_anomaly_scoring_tick_activity")
    async def fake_plan(input: AnomalyScoringTickInput) -> AnomalyScoringTickPlan:
        return plan

    @activity.defn(name="score_anomaly_insight_activity")
    async def fake_score(input: ScoreInsightInput) -> ScoreInsightResult:
        started.append(input.pick.insight_id)
        return ScoreInsightResult(status=statuses.get(input.pick.insight_id, "scored"), events=1)

    @activity.defn(name="capture_anomaly_scoring_tick_activity")
    async def fake_capture(result: AnomalyScoringTickResult) -> None:
        pass

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="anomaly-scoring-tick-test",
            workflows=[AnomalyScoringTickWorkflow],
            activities=[fake_plan, fake_score, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                AnomalyScoringTickWorkflow.run,
                AnomalyScoringTickInput(),
                id=f"anomaly-scoring-tick-{uuid.uuid4()}",
                task_queue="anomaly-scoring-tick-test",
            )
    return result, started


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statuses,started,queries,stopped",
    [
        ({}, [1, 2, 3, 4, 5], 15, False),
        # The second pick of the first wave finishes, and the tick starts no new pick.
        ({1: "at_capacity"}, [1, 2], 6, True),
    ],
)
async def test_the_tick_stops_starting_picks_when_clickhouse_is_at_capacity(
    statuses: dict[int, str], started: list[int], queries: int, stopped: bool
) -> None:
    plan = AnomalyScoringTickPlan(
        enabled=True,
        picks=[InsightPick(team_id=1, insight_id=i, scored_through={}, query_cost=3) for i in range(1, 6)],
        candidates=8,
        max_concurrency=2,
        skipped_for_budget=3,
    )

    result, ran = await _run_tick(plan, statuses)

    assert sorted(ran) == started
    assert (result.picked, result.queries, result.skipped_for_budget, result.stopped_at_capacity) == (
        len(started),
        queries,
        3,
        stopped,
    )
