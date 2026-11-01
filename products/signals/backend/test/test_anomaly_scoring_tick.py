import json
import uuid
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import IntervalType

from posthog.hogql.errors import QueryError, ResolutionError, TableAccessDeniedError

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models import Organization, Team, User
from posthog.tasks.alerts.detectors.base import ARTIFACT_SCHEMA_VERSION

from products.alerts.backend.models.alert import AlertConfiguration
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.api import record_insight_view
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.artifacts import clear_artifact_cache
from products.signals.backend.anomaly_scores.config import (
    DEFAULT_PROFILE,
    DISABLED,
    AnomalyScoringConfig,
    ScoringRun,
    covers_team,
    parse_config,
)
from products.signals.backend.anomaly_scores.emission import SCORER_DISTINCT_ID, score_events
from products.signals.backend.anomaly_scores.queue import (
    SKIP_COOLDOWN,
    ActiveInsight,
    ActivityReason,
    InsightPick,
    QueryBudget,
    TeamCensus,
    _cooldown_key,
    _fleet_budget_key,
    _project_budget_key,
    _team_loaded_key,
    active_insights,
    eligible_teams,
    is_due,
    remaining_budget,
    reserve_queries,
    scored_buckets,
    select_insights,
    within_budget,
)
from products.signals.backend.anomaly_scores.scoring import (
    InsightScores,
    ScoredPoint,
    ScoredSeries,
    StateIdentity,
    TrainedState,
    UnsupportedInsightError,
    interval_scoring,
    state_identity,
    trends_query_for,
)
from products.signals.backend.anomaly_scores.selection import SelectionConfig, Weighting
from products.signals.backend.anomaly_scores.state import RunPlan, load_state, plan_run, save_state
from products.signals.backend.anomaly_scores.tick import (
    AnomalyScoringTickInput,
    AnomalyScoringTickPlan,
    AnomalyScoringTickResult,
    AnomalyScoringTickWorkflow,
    ScoreInsightInput,
    ScoreInsightResult,
    capture_census,
    plan_tick,
    run_insight,
)
from products.signals.backend.models import AnomalyScoringState, SignalSourceConfig, SignalTeamConfig
from products.subscriptions.backend.facade.testing import create_subscription

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
                "self_driving_organization_percentage": 101,
                "deny_organization_ids": [ORGANIZATION_ID.upper(), "not-a-uuid", 3],
                "intervals": ["minute", "week"],
                "max_insights_per_tick": 0,
                "limits": {"max_backfill_buckets": 100_000, "max_series": -1},
                "train_score_split": "true",
                "train_every_buckets": {"hour": 100_000, "day": 0, "week": 2},
                "active_window_days": "30",
            }
        )

        assert config.organization_ids == (ORGANIZATION_ID,)
        assert config.allow_team_ids == (2,)
        assert config.self_driving_organization_percentage == 0.0
        assert config.deny_organization_ids == (ORGANIZATION_ID,)
        assert config.intervals == (IntervalType.WEEK,)
        assert config.max_insights_per_tick == DISABLED.max_insights_per_tick
        assert (config.limits.max_backfill_buckets, config.limits.max_series) == (90, 20)
        assert config.train_score_split is False
        assert config.train_every_buckets == {
            IntervalType.HOUR: 168,
            IntervalType.DAY: 7,
            IntervalType.WEEK: 2,
            IntervalType.MONTH: 3,
        }
        assert config.active_window_days == 90

    @parameterized.expand(
        [
            ("max_insights_per_tick", 51, 50),
            ("max_concurrency", 100, 8),
            ("max_queries_per_hour", 1_000_000, 2000),
            ("max_queries_per_project_per_hour", 501, 500),
            ("max_score_queries_per_hour", 1_000_000, 5000),
            ("max_score_queries_per_project_per_hour", 1001, 1000),
            ("max_score_insights_per_tick", 201, 200),
            ("max_train_insights_per_tick", 51, 50),
            ("active_window_days", 1000, 365),
        ]
    )
    def test_tick_levers_above_their_maximum_parse_to_the_maximum(self, field: str, value: int, expected: int) -> None:
        config = parse_config({"enabled": True, "organization_ids": [ORGANIZATION_ID], field: value})

        assert getattr(config, field) == expected

    @parameterized.expand(
        [
            ("defaults", {}, 20, 2),
            # A payload from before the split keeps its per-tick cap for train steps.
            ("only_the_old_cap", {"max_insights_per_tick": 8}, 20, 8),
            (
                "per_pass_caps",
                {"max_insights_per_tick": 8, "max_score_insights_per_tick": 40, "max_train_insights_per_tick": 3},
                40,
                3,
            ),
        ]
    )
    def test_each_pass_gets_its_own_cap(
        self, _name: str, levers: dict[str, int], score_cap: int, train_cap: int
    ) -> None:
        config = parse_config({**_SPLIT_PAYLOAD, **levers})

        assert (config.max_score_insights_per_tick, config.max_train_insights_per_tick) == (score_cap, train_cap)


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
            # The train budget is spent, and the score step of the second insight charges its own budget.
            (
                "score_step_uses_its_own_budget",
                {1: 1, 2: 1, 3: 1},
                QueryBudget(fleet=0, projects={1: 0}),
                10,
                [2],
                2,
                0,
                QueryBudget(fleet=5, projects={1: 5}),
            ),
            # A score step does not fit a spent score budget, even with train budget left.
            (
                "score_budget_spent",
                {1: 1, 2: 1, 3: 1},
                QueryBudget(fleet=100, projects={1: 30}),
                10,
                [1, 3],
                1,
                0,
                QueryBudget(fleet=0, projects={1: 0}),
            ),
            # The train pass passes over a score step, and does not count it as a budget skip.
            (
                "other_pass_kind_passed_over",
                {1: 1, 2: 1, 3: 1},
                QueryBudget(fleet=100, projects={1: 30}),
                10,
                [1, 3],
                0,
                0,
                None,
                ScoringRun.SCORE,
            ),
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
        score_budget: QueryBudget | None = None,
        second_run: ScoringRun | None = None,
    ) -> None:
        plans = {
            1: RunPlan(queries=3),
            2: RunPlan(queries=3, run=ScoringRun.SCORE if score_budget else second_run),
            3: RunPlan(queries=2),
        }
        budgets = {ScoringRun.TRAIN: budget}
        if score_budget is not None:
            budgets[ScoringRun.SCORE] = score_budget
        calls: list[RunPlan] = []

        def reserve(team_id: int, plan: RunPlan) -> bool:
            calls.append(plan)
            return len(calls) > refused_reservations

        picked, skipped_count = within_budget(
            [1, 2, 3], team_ids, budgets, limit, lambda ids: {i: plans[i] for i in ids}, reserve
        )

        assert (list(picked), skipped_count) == (expected, skipped)
        assert picked == {insight_id: plans[insight_id] for insight_id in expected}

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

        def plans_for(insight_ids: list[int]) -> dict[int, RunPlan]:
            batches.append(insight_ids)
            return dict.fromkeys(insight_ids, RunPlan(queries=1))

        within_budget(
            [1, 2, 3, 4],
            {1: 1, 2: 2, 3: 1, 4: 2},
            {ScoringRun.TRAIN: budget},
            10,
            plans_for,
            lambda _team, _plan: True,
        )

        assert batches == loaded

    @parameterized.expand([(ScoringRun.TRAIN, ScoringRun.SCORE), (ScoringRun.SCORE, ScoringRun.TRAIN)])
    def test_a_reservation_takes_both_budgets_or_neither_and_resets_each_hour(
        self, kind: ScoringRun, other: ScoringRun
    ) -> None:
        config = AnomalyScoringConfig(
            enabled=True,
            max_queries_per_hour=10,
            max_queries_per_project_per_hour=6,
            max_score_queries_per_hour=10,
            max_score_queries_per_project_per_hour=6,
        )
        next_hour = NOW + timedelta(hours=1)
        for now in (NOW, next_hour):
            for budget in ScoringRun:
                cache.delete_many(
                    [
                        _fleet_budget_key(now, budget),
                        _project_budget_key(1, now, budget),
                        _project_budget_key(2, now, budget),
                    ]
                )

        reserved = [
            reserve_queries(config, team_id, queries, NOW + timedelta(minutes=minute), kind)
            for team_id, queries, minute in [(1, 3, 0), (1, 3, 10), (1, 1, 20), (2, 4, 30), (2, 1, 40)]
        ]

        assert reserved == [True, True, False, True, False]
        assert remaining_budget(config, [1, 2], NOW, kind) == QueryBudget(fleet=0, projects={1: 0, 2: 2})
        assert remaining_budget(config, [1, 2], NOW, other) == QueryBudget(fleet=10, projects={1: 6, 2: 6})
        assert remaining_budget(config, [1, 2], next_hour, kind) == QueryBudget(fleet=10, projects={1: 6, 2: 6})


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
        insight = ActiveInsight(team_id=1, insight_id=7, interval=interval)

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
    def _run(self, error: Exception) -> tuple[str, list[Any], MagicMock, dict[str, Any]]:
        tick = "products.signals.backend.anomaly_scores.tick"
        client = MagicMock()
        capture = MagicMock()
        with (
            patch(f"{tick}.ph_background_capture", return_value=capture),
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
        [pick_event] = [
            call.kwargs for call in capture.call_args_list if call.kwargs["event"] == "anomaly scoring pick"
        ]
        return status, cooldowns, client.metrics, pick_event["properties"]

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
        status, cooldowns, metrics, pick_event = self._run(error)

        assert status == expected
        assert cooldowns[-1] == SKIP_COOLDOWN
        metrics.count.assert_any_call(
            "anomaly_scoring.picks", 1, attributes={"status": expected, "interval": IntervalType.DAY.value}
        )
        assert {key: pick_event[key] for key in ("team_id", "insight_id", "interval", "status", "queries")} == {
            "team_id": 1,
            "insight_id": 7,
            "interval": IntervalType.DAY.value,
            "status": expected,
            "queries": 1,
        }

    def test_a_full_cluster_returns_at_capacity_and_waits_an_hour(self) -> None:
        status, cooldowns, _metrics, _pick_event = self._run(ClickHouseAtCapacity())

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
        status, cooldowns, _metrics, pick_event = self._run(error)

        assert status == "raised"
        assert SKIP_COOLDOWN not in cooldowns
        assert pick_event["status"] == "errored"


class TestCaptureCensus(SimpleTestCase):
    def test_each_team_gets_one_census_event_per_utc_day(self) -> None:
        census = [
            TeamCensus(team_id=team_id, active=1, active_reasons={"viewed": 1}, active_intervals={"day": 1})
            for team_id in (901, 902)
        ]
        days = [NOW, NOW + timedelta(hours=11), NOW + timedelta(days=1)]
        cache.delete_many(
            [
                f"signals:anomaly_scoring:census:{day.date().isoformat()}:{team_id}"
                for day in days
                for team_id in (901, 902)
            ]
        )
        capture = MagicMock()

        with patch("products.signals.backend.anomaly_scores.tick.ph_background_capture", return_value=capture):
            for now in days:
                capture_census(census, now)

        sent = [
            (call.kwargs["properties"]["day"], call.kwargs["properties"]["team_id"]) for call in capture.call_args_list
        ]
        assert sent == [("2026-10-22", 901), ("2026-10-22", 902), ("2026-10-23", 901), ("2026-10-23", 902)]


class TestTrainScoreSplit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "UTC"
        self.team.save()
        self.blobs: dict[str, bytes] = {}
        storage = "products.signals.backend.anomaly_scores.artifacts.object_storage"
        for name, fake in [
            ("write", lambda key, blob: self.blobs.__setitem__(key, blob)),
            ("read_bytes", lambda key, missing_ok: self.blobs.get(key)),
            ("delete", lambda key: self.blobs.pop(key, None)),
        ]:
            patcher = patch(f"{storage}.{name}", side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        clear_artifact_cache()
        self.addCleanup(clear_artifact_cache)

    def _run(
        self, insight: Insight, pick: InsightPick, now: datetime, data: list[float]
    ) -> tuple[ScoreInsightResult, list[dict[str, Any]]]:
        days = [(now - timedelta(days=len(data) - 1 - day)).strftime("%Y-%m-%d") for day in range(len(data))]
        results = [{"order": 0, "label": "pageview", "days": days, "data": data, "breakdown_value": None}]
        with (
            patch("products.signals.backend.anomaly_scores.scoring.TrendsQueryRunner") as runner,
            patch("products.signals.backend.anomaly_scores.tick.emit") as emit,
            patch("products.signals.backend.anomaly_scores.tick.mark_attempted"),
        ):
            runner.return_value.run.return_value = MagicMock(results=results)
            result = run_insight(ScoreInsightInput(pick=pick), now)
        return result, emit.call_args.args[1] if emit.called else []

    def _train(self, insight: Insight, trained_at: datetime) -> list[dict[str, Any]]:
        values = [float(value) for value in np.random.default_rng(4).normal(100, 5, size=100)]
        _result, events = self._run(
            insight,
            InsightPick(team_id=self.team.id, insight_id=insight.id, scored_through={}, run=ScoringRun.TRAIN),
            trained_at,
            values,
        )
        self.values = values
        return events

    def _score_pick(self, insight: Insight, trained: list[dict[str, Any]]) -> InsightPick:
        return InsightPick(
            team_id=self.team.id,
            insight_id=insight.id,
            scored_through={trained[-1]["properties"]["$anomaly_series_key"]: datetime(2026, 10, 19, tzinfo=UTC)},
            run=ScoringRun.SCORE,
        )

    def test_a_train_pick_stores_the_artifact_that_the_next_score_pick_scores_with(self) -> None:
        insight = Insight.objects.create(team=self.team, saved=True, query=_trends(interval="day"))
        trained_at = datetime(2026, 10, 20, 0, 30, tzinfo=UTC)
        trained = self._train(insight, trained_at)
        first_key = AnomalyScoringState.objects.for_team(self.team.id).get(insight_id=insight.id).artifact_key
        _result, scored = self._run(
            insight,
            self._score_pick(insight, trained),
            trained_at + timedelta(days=2),
            [*self.values[-4:], 500.0, 100.0],
        )
        self._train(insight, trained_at + timedelta(days=7))

        assert {event["properties"]["$anomaly_run"] for event in trained} == {"train"}
        assert [
            (
                event["properties"]["$anomaly_run"],
                event["properties"]["$anomaly_bucket_start"],
                event["properties"]["$anomaly_flag"],
            )
            for event in scored
        ] == [("score", "2026-10-20T00:00:00+00:00", 0), ("score", "2026-10-21T00:00:00+00:00", 1)]
        # A score step names the train time of its model, so a reader can tell a stale-model score apart.
        assert {event["properties"]["$anomaly_trained_at"] for event in scored} == {trained_at.isoformat()}
        model_ids = {event["properties"]["$anomaly_model_id"] for event in [*trained, *scored]}
        assert model_ids == {first_key.rsplit("/", 1)[-1]}
        state = AnomalyScoringState.objects.for_team(self.team.id).get(insight_id=insight.id)
        assert state.trained_at == trained_at + timedelta(days=7)
        # A retrain replaces the blob and deletes the previous one.
        assert list(self.blobs) == [state.artifact_key] != [first_key]

    @parameterized.expand([("corrupt",), ("missing",), ("older_schema",)])
    def test_an_artifact_blob_that_fails_its_check_makes_the_next_visit_train(self, case: str) -> None:
        insight = Insight.objects.create(team=self.team, saved=True, query=_trends(interval="day"))
        trained_at = datetime(2026, 10, 20, 0, 30, tzinfo=UTC)
        trained = self._train(insight, trained_at)
        state = AnomalyScoringState.objects.for_team(self.team.id).get(insight_id=insight.id)
        key = state.artifact_key
        clear_artifact_cache()
        if case == "missing":
            del self.blobs[key]
        elif case == "corrupt":
            self.blobs[key] = b"{}"
        else:
            stored = json.loads(self.blobs[key])
            for artifact in stored["series"].values():
                artifact["schema_version"] = ARTIFACT_SCHEMA_VERSION - 1
            self.blobs[key] = json.dumps(stored).encode()
            state.artifact_sha256 = hashlib.sha256(self.blobs[key]).hexdigest()
            state.save()
        scored_at = trained_at + timedelta(days=2)

        result, events = self._run(insight, self._score_pick(insight, trained), scored_at, self.values[-6:])

        assert (result.status, events) == ("artifact_unavailable", [])
        plan = plan_run(insight, self.team, load_state(self.team, insight), parse_config(_SPLIT_PAYLOAD), scored_at)
        assert plan.run == ScoringRun.TRAIN


_SPLIT_PAYLOAD = {"enabled": True, "organization_ids": [ORGANIZATION_ID], "train_score_split": True}


class TestEligibleTeams(BaseTest):
    @parameterized.expand(
        [
            ("every_team_of_the_organization", [], [], False, None, {"main", "second"}),
            ("allowlist", ["main"], [], False, None, {"main"}),
            ("skip_list", [], ["main"], False, None, {"second"}),
            ("quota_limited", [], [], True, None, {"main"}),
            ("turned_off_in_settings", [], [], False, False, {"main"}),
            ("left_on_in_settings", [], [], False, True, {"main", "second"}),
            ("settings_cannot_enroll_a_skipped_team", [], ["second"], False, True, {"main"}),
        ]
    )
    def test_only_allowed_teams_under_their_event_quota_are_scored(
        self,
        _name: str,
        allow: list[str],
        skip: list[str],
        second_limited: bool,
        second_setting: bool | None,
        expected: set[str],
    ) -> None:
        teams = {"main": self.team, "second": Team.objects.create(organization=self.organization, name="second")}
        if second_setting is not None:
            SignalTeamConfig.objects.create(team=teams["second"], anomaly_scoring_enabled=second_setting)
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

    @parameterized.expand(
        [
            # name, listed, percentage, denied, skipped, allow_other, has_source, enrolled
            ("listed_without_source", True, 0.0, False, False, False, False, True),
            ("listed_and_denied", True, 0.0, True, False, False, False, False),
            ("rollout", False, 100.0, False, False, False, True, True),
            ("rollout_without_source", False, 100.0, False, False, False, False, False),
            ("rollout_at_zero", False, 0.0, False, False, False, True, False),
            ("rollout_denied", False, 100.0, True, False, False, True, False),
            ("rollout_team_skipped", False, 100.0, False, True, False, True, False),
            ("rollout_ignores_the_allowlist", False, 100.0, False, False, True, True, True),
        ]
    )
    def test_enrollment_by_list_and_rollout(
        self,
        _name: str,
        listed: bool,
        percentage: float,
        denied: bool,
        skipped: bool,
        allow_other: bool,
        has_source: bool,
        enrolled: bool,
    ) -> None:
        other = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        own_organization = (str(self.organization.id),)
        config = AnomalyScoringConfig(
            enabled=True,
            organization_ids=own_organization if listed else (),
            self_driving_organization_percentage=percentage,
            deny_organization_ids=own_organization if denied else (),
            skip_team_ids=(self.team.id,) if skipped else (),
            allow_team_ids=(other.id,) if allow_other else (),
        )
        if has_source:
            SignalSourceConfig.objects.create(
                team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
            )

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            eligible = {team.id for team in eligible_teams(config)}

        assert covers_team(config, Team.objects.get(id=self.team.id)) is enrolled
        assert (self.team.id in eligible) is enrolled
        assert other.id not in eligible

    def test_rollout_skips_a_team_that_turned_scoring_off(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        SignalTeamConfig.objects.create(team=self.team, anomaly_scoring_enabled=False)
        config = AnomalyScoringConfig(enabled=True, self_driving_organization_percentage=100.0)

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            assert self.team.id not in {team.id for team in eligible_teams(config)}


_DEFAULT_INTERVALS = (IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH)
_LONG_AGO = NOW - timedelta(days=91)


class TestActiveInsights(BaseTest):
    @time_machine.travel(NOW, tick=False)
    def test_only_time_series_trends_with_a_scored_interval_are_eligible(self) -> None:
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=query)
            for name, query in {
                "day": _trends(interval="day"),
                "week": _trends(interval="week"),
                "default_interval": _trends(),
                "hourly": _trends(interval="hour"),
                "funnel": {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}},
                "bold_number": _trends(interval="day", trendsFilter={"display": "BoldNumber"}),
                "cumulative": _trends(interval="day", trendsFilter={"display": "ActionsLineGraphCumulative"}),
            }.items()
        }

        active = active_insights([self.team.id], _DEFAULT_INTERVALS, NOW, 90)

        names = {insight.id: name for name, insight in insights.items()}
        assert {(names[insight.insight_id], insight.interval) for insight in active} == {
            ("day", IntervalType.DAY),
            ("week", IntervalType.WEEK),
            ("default_interval", IntervalType.DAY),
        }

    @parameterized.expand(
        [
            ("viewed", {ActivityReason.VIEWED}),
            ("viewed_anonymously", set()),
            ("viewed_before_the_window", set()),
            ("on_an_accessed_dashboard", {ActivityReason.DASHBOARD_ACCESSED}),
            ("on_a_dashboard_nobody_opened", set()),
            ("on_a_dashboard_opened_before_the_window", set()),
            ("hidden_tile_on_an_accessed_dashboard", set()),
            ("enabled_alert", {ActivityReason.ENABLED_ALERT}),
            ("disabled_alert", set()),
            ("subscription", {ActivityReason.ACTIVE_SUBSCRIPTION}),
            ("dashboard_subscription", {ActivityReason.ACTIVE_SUBSCRIPTION}),
            ("disabled_subscription", set()),
            ("edited", {ActivityReason.EDITED}),
            ("viewed_and_edited", {ActivityReason.VIEWED, ActivityReason.EDITED}),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_an_insight_is_active_only_with_a_signal_in_the_window(
        self, signal: str, expected: set[ActivityReason]
    ) -> None:
        insight = Insight.objects.create(team=self.team, name="insight", query=_trends(interval="day"))
        Insight.objects.filter(id=insight.id).update(last_modified_at=_LONG_AGO)
        dashboard = Dashboard.objects.create(team=self.team, name="Main", last_accessed_at=NOW - timedelta(days=1))

        if signal in ("viewed", "viewed_and_edited"):
            record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=self.user.id)
        elif signal == "viewed_anonymously":
            record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=None)
        elif signal == "viewed_before_the_window":
            with time_machine.travel(_LONG_AGO, tick=False):
                record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=self.user.id)
        elif signal == "on_an_accessed_dashboard":
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        elif signal in ("on_a_dashboard_nobody_opened", "on_a_dashboard_opened_before_the_window"):
            dashboard.last_accessed_at = None if signal == "on_a_dashboard_nobody_opened" else _LONG_AGO
            dashboard.save(update_fields=["last_accessed_at"])
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        elif signal == "hidden_tile_on_an_accessed_dashboard":
            DashboardTile.objects.create(dashboard=dashboard, insight=insight, deleted=True)
        elif signal in ("enabled_alert", "disabled_alert"):
            AlertConfiguration.objects.create(
                team=self.team, insight=insight, name="alert", enabled=signal == "enabled_alert"
            )
        elif signal in ("subscription", "disabled_subscription"):
            create_subscription(team_id=self.team.id, insight_id=insight.id, enabled=signal == "subscription")
        elif signal == "dashboard_subscription":
            dashboard.last_accessed_at = None
            dashboard.save(update_fields=["last_accessed_at"])
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            create_subscription(team_id=self.team.id, dashboard_id=dashboard.id)
        if signal in ("edited", "viewed_and_edited"):
            Insight.objects.filter(id=insight.id).update(last_modified_at=NOW - timedelta(days=1))

        active = active_insights([self.team.id], _DEFAULT_INTERVALS, NOW, 90)

        assert {insight.insight_id: set(insight.reasons) for insight in active} == (
            {insight.id: expected} if expected else {}
        )

    def test_an_insight_drops_out_when_its_signal_ages_out_and_comes_back_with_a_new_one(self) -> None:
        insight = Insight.objects.create(team=self.team, name="insight", query=_trends(interval="day"))
        Insight.objects.filter(id=insight.id).update(last_modified_at=_LONG_AGO)
        with time_machine.travel(NOW - timedelta(days=29), tick=False):
            record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=self.user.id)

        assert [active.insight_id for active in active_insights([self.team.id], _DEFAULT_INTERVALS, NOW, 30)] == [
            insight.id
        ]
        later = NOW + timedelta(days=2)
        assert active_insights([self.team.id], _DEFAULT_INTERVALS, later, 30) == []

        with time_machine.travel(later, tick=False):
            record_insight_view(insight_id=insight.id, team_id=self.team.id, user_id=self.user.id)

        assert [active.insight_id for active in active_insights([self.team.id], _DEFAULT_INTERVALS, later, 30)] == [
            insight.id
        ]


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
        # Inside the window of the other insights, but older than the window of its own interval.
        score(12, "g", datetime(2026, 9, 15, tzinfo=UTC))

        state = scored_buckets(
            self.team,
            {datetime(2026, 9, 1, tzinfo=UTC): {7, 8, 9, 10}, datetime(2026, 10, 1, tzinfo=UTC): {12}},
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
            for name in ("never_scored", "stale", "fresh", "past_day_window", "inactive")
        }
        for insight in insights.values():
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            cache.delete(_cooldown_key(insight.id))
        # Never scored, so it would go first, but nobody opened its dashboard and nobody touched it in the window.
        Insight.objects.filter(id=insights["inactive"].id).update(last_modified_at=_LONG_AGO)
        cache.delete_many([_fleet_budget_key(NOW), _project_budget_key(self.team.id, NOW)])
        today = NOW.replace(hour=0)
        for name, bucket in (
            ("stale", today - timedelta(days=3)),
            ("fresh", today - timedelta(days=1)),
            # Inside the window of a month insight, but older than the window of a day insight.
            ("past_day_window", today - timedelta(days=40)),
        ):
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

        picks = {pick.insight_id: pick for pick in selection.picks}
        assert set(picks) == {insights[name].id for name in ("never_scored", "stale", "past_day_window")}
        assert (selection.active, selection.active_reasons) == (
            4,
            {reason.value: 4 if reason == ActivityReason.EDITED else 0 for reason in ActivityReason},
        )
        assert picks[insights["stale"].id].scored_through == {"stale": today - timedelta(days=3)}
        assert picks[insights["past_day_window"].id].scored_through == {}

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
        assert [(team.team_id, team.active, team.active_intervals) for team in selection.census] == [
            (self.team.id, 3, {"day": 3}),
            (small_team.id, 1, {"day": 1}),
        ]

    @parameterized.expand([("query_timeout", ClickHouseQueryTimeOut), ("at_capacity", ClickHouseAtCapacity)])
    @time_machine.travel(NOW, tick=False)
    def test_select_insights_skips_a_project_whose_scored_buckets_query_fails(
        self, _name: str, error: type[Exception]
    ) -> None:
        slow_team = Team.objects.create(organization=self.organization, name="Slow")
        dashboards = {team.id: Dashboard.objects.create(team=team, name="Main") for team in (self.team, slow_team)}
        insights = {}
        for team in (self.team, slow_team):
            insight = Insight.objects.create(team=team, name=team.name, query=_trends(interval="day"))
            DashboardTile.objects.create(dashboard=dashboards[team.id], insight=insight)
            cache.delete(_cooldown_key(insight.id))
            insights[team.id] = insight
        cache.delete_many(
            [_fleet_budget_key(NOW), *(_project_budget_key(team_id, NOW) for team_id in (self.team.id, slow_team.id))]
        )
        config = AnomalyScoringConfig(
            enabled=True,
            organization_ids=(str(self.organization.id),),
            allow_team_ids=(self.team.id, slow_team.id),
        )

        def buckets(team: Team, *args: Any) -> dict[int, dict[str, datetime]]:
            if team.id == slow_team.id:
                raise error()
            return scored_buckets(team, *args)

        with (
            patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]),
            patch("products.signals.backend.anomaly_scores.queue.scored_buckets", side_effect=buckets),
        ):
            selection = select_insights(config, SelectionConfig(weighting=Weighting.UNIFORM), NOW, limit=10)

        assert [pick.insight_id for pick in selection.picks] == [insights[self.team.id].id]
        assert (selection.teams_planned, selection.teams_skipped) == (1, 1)

    @time_machine.travel(NOW, tick=False)
    def test_a_plan_past_its_deadline_loads_one_team_and_the_next_plan_starts_from_another(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        insights = {}
        for team in (self.team, other_team):
            insight = Insight.objects.create(team=team, name=team.name, query=_trends(interval="day"))
            DashboardTile.objects.create(dashboard=Dashboard.objects.create(team=team, name="Main"), insight=insight)
            cache.delete_many([_cooldown_key(insight.id), _team_loaded_key(team.id)])
            insights[team.id] = insight.id
        config = AnomalyScoringConfig(
            enabled=True,
            organization_ids=(str(self.organization.id),),
            allow_team_ids=(self.team.id, other_team.id),
        )

        picked: list[list[int]] = []
        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            for later in (NOW, NOW + timedelta(minutes=5)):
                cache.delete_many(
                    [_fleet_budget_key(later), *(_project_budget_key(team_id, later) for team_id in insights)]
                )
                selection = select_insights(
                    config, SelectionConfig(weighting=Weighting.UNIFORM), later, limit=10, deadline=0.0
                )
                assert (selection.teams_planned, selection.teams_skipped) == (1, 1)
                picked.append([pick.insight_id for pick in selection.picks])

        assert sorted(insight_id for picks in picked for insight_id in picks) == sorted(insights.values())

    @parameterized.expand([("cap_one", 1, ["most_overdue"]), ("cap_two", 2, ["most_overdue", "popular"])])
    @time_machine.travel(NOW, tick=False)
    def test_the_score_pass_picks_trained_insights_most_overdue_first_with_the_train_budget_spent(
        self, _name: str, score_cap: int, expected: list[str]
    ) -> None:
        self.team.timezone = "UTC"
        self.team.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=_trends(interval="day"))
            for name in ("most_overdue", "popular", "untrained")
        }
        for insight in insights.values():
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            cache.delete(_cooldown_key(insight.id))
        for viewer_index in range(5):
            viewer = User.objects.create_and_join(self.organization, f"viewer{viewer_index}@example.com", "password")
            record_insight_view(insight_id=insights["popular"].id, team_id=self.team.id, user_id=viewer.id)
        config = parse_config(
            {
                **_SPLIT_PAYLOAD,
                "organization_ids": [str(self.organization.id)],
                "allow_team_ids": [self.team.id],
                "max_score_insights_per_tick": score_cap,
            }
        )
        today = NOW.replace(hour=0)
        for name, scored_through in (
            ("most_overdue", today - timedelta(days=4)),
            ("popular", today - timedelta(days=2)),
        ):
            insight = insights[name]
            query = trends_query_for(insight, DEFAULT_PROFILE)
            identity = state_identity(
                query, interval_scoring(DEFAULT_PROFILE, IntervalType.DAY), self.team, config.limits
            )
            save_state(
                self.team,
                insight.id,
                DEFAULT_PROFILE.name,
                TrainedState(
                    identity=identity,
                    trained_at=NOW - timedelta(days=1),
                    scored_through=scored_through,
                    series_keys=("a",),
                    artifact_key=f"anomaly_models/{insight.id}",
                ),
            )
        for kind in ScoringRun:
            cache.delete_many([_fleet_budget_key(NOW, kind), _project_budget_key(self.team.id, NOW, kind)])
        cache.set(_fleet_budget_key(NOW, ScoringRun.TRAIN), config.max_queries_per_hour)

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            selection = select_insights(config, SelectionConfig(), NOW)

        names = {insight.id: name for name, insight in insights.items()}
        assert [(names[pick.insight_id], pick.run) for pick in selection.picks] == [
            (name, ScoringRun.SCORE) for name in expected
        ]
        assert (selection.picked_score, selection.picked_train) == (len(expected), 0)

    @parameterized.expand(
        [
            ("score_budget_left", False, [("current", ScoringRun.SCORE), ("edited", ScoringRun.TRAIN)]),
            ("score_budget_spent", True, [("edited", ScoringRun.TRAIN)]),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_an_edited_insight_with_a_current_state_goes_to_the_train_pass(
        self, _name: str, score_budget_spent: bool, expected: list[tuple[str, ScoringRun]]
    ) -> None:
        self.team.timezone = "UTC"
        self.team.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=_trends(interval="day"))
            for name in ("edited", "current")
        }
        for insight in insights.values():
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            cache.delete(_cooldown_key(insight.id))
        config = parse_config(
            {**_SPLIT_PAYLOAD, "organization_ids": [str(self.organization.id)], "allow_team_ids": [self.team.id]}
        )
        today = NOW.replace(hour=0)
        for name, scored_through in (("edited", today - timedelta(days=4)), ("current", today - timedelta(days=2))):
            insight = insights[name]
            identity = state_identity(
                trends_query_for(insight, DEFAULT_PROFILE),
                interval_scoring(DEFAULT_PROFILE, IntervalType.DAY),
                self.team,
                config.limits,
            )
            if name == "edited":
                identity = StateIdentity(
                    interval=identity.interval, detector_version=identity.detector_version, query_hash="before-edit"
                )
            save_state(
                self.team,
                insight.id,
                DEFAULT_PROFILE.name,
                TrainedState(
                    identity=identity,
                    trained_at=NOW - timedelta(days=1),
                    scored_through=scored_through,
                    series_keys=("a",),
                    artifact_key=f"anomaly_models/{insight.id}",
                ),
            )
        for kind in ScoringRun:
            cache.delete_many([_fleet_budget_key(NOW, kind), _project_budget_key(self.team.id, NOW, kind)])
        if score_budget_spent:
            cache.set(_fleet_budget_key(NOW, ScoringRun.SCORE), config.max_score_queries_per_hour)

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            selection = select_insights(config, SelectionConfig(), NOW)

        names = {insight.id: name for name, insight in insights.items()}
        assert [(names[pick.insight_id], pick.run) for pick in selection.picks] == expected

    @parameterized.expand(
        [
            (
                "train_budget_spent",
                True,
                [("past_train_every", ScoringRun.SCORE)],
                (1, 1, 1),
            ),
            (
                "train_budget_left",
                False,
                [("past_age_ceiling", ScoringRun.TRAIN), ("past_train_every", ScoringRun.TRAIN)],
                (0, 0, 0),
            ),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_a_model_past_train_every_keeps_scoring_until_the_train_pass_has_budget_for_it(
        self,
        _name: str,
        train_budget_spent: bool,
        expected: list[tuple[str, ScoringRun]],
        stale_and_backlog: tuple[int, int, int],
    ) -> None:
        self.team.timezone = "UTC"
        self.team.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Main")
        insights = {
            name: Insight.objects.create(team=self.team, name=name, query=_trends(interval="day"))
            for name in ("past_train_every", "past_age_ceiling")
        }
        for insight in insights.values():
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            cache.delete(_cooldown_key(insight.id))
        config = parse_config(
            {**_SPLIT_PAYLOAD, "organization_ids": [str(self.organization.id)], "allow_team_ids": [self.team.id]}
        )
        today = NOW.replace(hour=0)
        for name, trained_days_ago in (("past_train_every", 10), ("past_age_ceiling", 30)):
            insight = insights[name]
            save_state(
                self.team,
                insight.id,
                DEFAULT_PROFILE.name,
                TrainedState(
                    identity=state_identity(
                        trends_query_for(insight, DEFAULT_PROFILE),
                        interval_scoring(DEFAULT_PROFILE, IntervalType.DAY),
                        self.team,
                        config.limits,
                    ),
                    trained_at=NOW - timedelta(days=trained_days_ago),
                    scored_through=today - timedelta(days=2),
                    series_keys=("a",),
                    artifact_key=f"anomaly_models/{insight.id}",
                ),
            )
        for kind in ScoringRun:
            cache.delete_many([_fleet_budget_key(NOW, kind), _project_budget_key(self.team.id, NOW, kind)])
        if train_budget_spent:
            cache.set(_fleet_budget_key(NOW, ScoringRun.TRAIN), config.max_queries_per_hour)

        with patch("products.signals.backend.anomaly_scores.queue.list_limited_team_attributes", return_value=[]):
            selection = select_insights(config, SelectionConfig(weighting=Weighting.UNIFORM), NOW)

        names = {insight.id: name for name, insight in insights.items()}
        assert sorted((names[pick.insight_id], pick.run) for pick in selection.picks) == expected
        assert (
            selection.scored_stale_model,
            selection.train_backlog_soft,
            selection.train_backlog_hard,
        ) == stale_and_backlog


async def _run_tick(
    plan: AnomalyScoringTickPlan | Exception,
    statuses: dict[int, str],
    captured: list[AnomalyScoringTickResult] | None = None,
) -> tuple[AnomalyScoringTickResult, list[int]]:
    started: list[int] = []

    @activity.defn(name="plan_anomaly_scoring_tick_activity")
    async def fake_plan(input: AnomalyScoringTickInput) -> AnomalyScoringTickPlan:
        if isinstance(plan, Exception):
            raise plan
        return plan

    @activity.defn(name="score_anomaly_insight_activity")
    async def fake_score(input: ScoreInsightInput) -> ScoreInsightResult:
        started.append(input.pick.insight_id)
        return ScoreInsightResult(status=statuses.get(input.pick.insight_id, "scored"), events=1)

    @activity.defn(name="capture_anomaly_scoring_tick_activity")
    async def fake_capture(result: AnomalyScoringTickResult) -> None:
        if captured is not None:
            captured.append(result)

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


@pytest.mark.asyncio
async def test_a_failed_plan_sends_a_tick_event_and_still_fails_the_workflow() -> None:
    captured: list[AnomalyScoringTickResult] = []

    with pytest.raises(WorkflowFailureError):
        await _run_tick(ClickHouseAtCapacity(), {}, captured)

    assert [(result.plan_failed, result.plan_error, result.picked) for result in captured] == [
        (True, "ClickHouseAtCapacity", 0)
    ]
