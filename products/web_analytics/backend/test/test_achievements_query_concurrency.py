from datetime import date

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import fakeredis
from clickhouse_driver.errors import NetworkError
from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.schema import HogQLQueryResponse

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models.team.team import Team

from products.web_analytics.backend.achievements import evaluators, tasks
from products.web_analytics.backend.achievements.definitions import TRACKS, TrackKey
from products.web_analytics.backend.achievements.evaluators import EvalContext, PriorProgress
from products.web_analytics.backend.achievements.query_concurrency import get_achievement_query_limiter

CAPACITY_ERRORS = [
    ("concurrency", ConcurrencyLimitExceeded),
    ("capacity", ClickHouseAtCapacity),
    ("network", NetworkError),
    ("redis", RedisConnectionError),
]


class TestAchievementQueryConcurrency(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        get_achievement_query_limiter.cache_clear()
        self.addCleanup(get_achievement_query_limiter.cache_clear)
        self.limiter = get_achievement_query_limiter()
        self.limiter.redis_client = fakeredis.FakeRedis()
        self.clock_start = 1_000_000.0
        self.clock = self.clock_start
        self.limiter.get_time = lambda: self.clock
        self.limiter.sleep = self._advance_clock
        self.team = Team(pk=12)
        self.ctx = EvalContext(team=self.team, user=None, today=date(2026, 1, 2), arm=None)
        self.prior = PriorProgress(value=0, last_computed_at=None, checkpoint={})

    def _advance_clock(self, seconds: float) -> None:
        self.clock += seconds

    def _fill_budget(self) -> list[ConcurrencySlot]:
        slots = [self.limiter.use(team_id=team_id) for team_id in range(self.limiter.max_concurrency)]
        return [slot for slot in slots if slot is not None]

    def test_full_shared_budget_fails_fast_without_executing_a_query(self) -> None:
        slots = self._fill_budget()
        with (
            patch.object(evaluators, "_project_environment_teams", return_value=[self.team]),
            patch.object(
                evaluators, "execute_hogql_query", return_value=HogQLQueryResponse(results=[[123]])
            ) as execute,
        ):
            with self.assertRaises(ConcurrencyLimitExceeded):
                evaluators.evaluate_cumulative_pageviews(self.ctx, self.prior)
            execute.assert_not_called()
            self.assertEqual(self.clock, self.clock_start)
            self.limiter.release(slots.pop())
            self.assertEqual(evaluators.evaluate_cumulative_pageviews(self.ctx, self.prior).value, 123)
            execute.assert_called_once()

    def test_multi_environment_project_holds_one_slot_for_all_its_queries(self) -> None:
        environments = [self.team, Team(pk=13)]
        with (
            patch.object(evaluators, "_project_environment_teams", return_value=environments),
            patch.object(evaluators, "execute_hogql_query", return_value=HogQLQueryResponse(results=[[5]])),
            patch.object(self.limiter, "use", wraps=self.limiter.use) as use,
        ):
            self.assertEqual(evaluators.evaluate_cumulative_pageviews(self.ctx, self.prior).value, 10)
            use.assert_called_once()

    def test_query_exception_releases_its_slot_for_the_next_project(self) -> None:
        with (
            patch.object(evaluators, "_project_environment_teams", return_value=[self.team]),
            patch.object(evaluators, "execute_hogql_query", side_effect=RuntimeError("Query failed")),
        ):
            with self.assertRaisesMessage(RuntimeError, "Query failed"):
                evaluators.evaluate_cumulative_pageviews(self.ctx, self.prior)
        self.assertEqual(self.limiter.redis_client.zcard(self.limiter.get_task_name()), 0)

    def test_conversions_use_the_same_budget_as_pageviews(self) -> None:
        self._fill_budget()
        with (
            patch.object(evaluators.Action, "objects") as actions,
            patch.object(evaluators, "_project_environment_teams", return_value=[self.team]),
            patch.object(evaluators, "action_to_expr", return_value=evaluators.ast.Constant(value=True)),
            patch.object(evaluators, "execute_hogql_query") as execute,
        ):
            actions.filter.return_value.order_by.return_value.__getitem__.return_value = [Mock()]
            with self.assertRaises(ConcurrencyLimitExceeded):
                evaluators.evaluate_conversions(self.ctx, self.prior)
            execute.assert_not_called()

    def test_redis_failure_does_not_bypass_the_query_budget(self) -> None:
        with (
            patch.object(self.limiter.redis_client, "eval", side_effect=RedisConnectionError("Redis unavailable")),
            patch.object(evaluators, "_project_environment_teams", return_value=[self.team]),
            patch.object(evaluators, "execute_hogql_query") as execute,
        ):
            with self.assertRaises(RedisConnectionError):
                evaluators.evaluate_cumulative_pageviews(self.ctx, self.prior)
            execute.assert_not_called()

    @parameterized.expand(CAPACITY_ERRORS)
    def test_capacity_failures_propagate_without_marking_progress_complete(
        self, _name: str, error_type: type[Exception]
    ) -> None:
        evaluator = Mock(side_effect=error_type("Unavailable"))
        progress = Mock(current_stage=0, last_computed_at=None, progress_value=0, state={})
        with (
            patch.object(tasks, "get_or_create_progress", return_value=progress),
            patch.dict(tasks.INCREMENTAL_EVALUATORS, {"cumulative_pageviews": evaluator}),
            patch.object(tasks, "_apply_progress") as apply_progress,
        ):
            with self.assertRaises(error_type):
                tasks._recompute_track(self.ctx, TRACKS[TrackKey.TRAFFIC])
            apply_progress.assert_not_called()

    @parameterized.expand(CAPACITY_ERRORS)
    def test_task_leaves_capacity_failures_to_the_next_sweep_instead_of_retrying(
        self, _name: str, error_type: type[Exception]
    ) -> None:
        with (
            patch.object(tasks, "recompute_web_analytics_achievements_sync", side_effect=error_type("Busy")),
            patch.object(tasks.recompute_web_analytics_achievements, "retry") as retry,
        ):
            tasks.recompute_web_analytics_achievements.run(self.team.id)
        retry.assert_not_called()
