from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import CompareFilter, DateRange, HogQLQueryModifiers, MarketingAnalyticsTableQuery

from posthog import redis
from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags, tags_context
from posthog.models import Team
from posthog.models.event.new_events_schema import events_route_scope, new_events_schema_for_request
from posthog.redis import TEST_clear_clients
from posthog.token_bucket import TEST_reset_scripts

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    ServedWindow,
)
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import (
    ENQUEUE_FAILURE_BACKOFF_SECONDS,
    PRECOMPUTE_ONLY_MAX_STALE_SECONDS,
    REVALIDATION_TRIGGER,
    TEAM_WARM_BUDGET,
    _query_shape_key,
    _revalidation_query,
    costs_latest_day_computed_at,
    events_latest_day_computed_at,
    handle_not_ready,
    handle_stale_served,
    marketing_ensure_precomputed,
)

_MODULE = "products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute"
_DELAY = (
    "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation"
    ".revalidate_marketing_analytics_precompute.delay"
)


_T0 = datetime(2024, 3, 1, tzinfo=UTC)
_T1 = datetime(2024, 3, 5, 1, tzinfo=UTC)
_T2 = datetime(2024, 3, 5, 9, tzinfo=UTC)


def _utc_day_window(day: int, computed_at: datetime | None) -> ServedWindow:
    return ServedWindow(
        start=datetime(2024, 3, day, tzinfo=UTC), end=datetime(2024, 3, day + 1, tzinfo=UTC), computed_at=computed_at
    )


class TestLatestDayComputedAt(SimpleTestCase):
    @parameterized.expand(
        [
            # Local Mar 5 starts at Mar 4 22:00 UTC, so the Mar 4 UTC window holds its first hours.
            ("ahead_of_utc", "Asia/Jerusalem", [(3, _T0), (4, _T1), (5, _T2)], _T1),
            # Local Mar 5 starts at Mar 5 08:00 UTC, so the Mar 4 UTC window holds none of it.
            ("behind_utc", "America/Los_Angeles", [(4, _T0), (5, _T2), (6, _T1)], _T1),
            ("unknown_stamp_on_latest_day", "UTC", [(4, _T0), (5, None)], None),
        ]
    )
    def test_events_take_the_oldest_window_holding_the_local_latest_day(self, _name, timezone, windows, expected):
        latest_day_start = datetime(2024, 3, 5, tzinfo=ZoneInfo(timezone))
        served = [_utc_day_window(day, stamp) for day, stamp in windows]

        assert events_latest_day_computed_at(served, latest_day_start) == expected

    def test_costs_take_only_the_window_holding_the_cost_day(self):
        served = [_utc_day_window(4, _T0), _utc_day_window(5, _T2)]

        assert costs_latest_day_computed_at(served, date(2024, 3, 5)) == _T2


class TestMarketingRevalidationEventsTable(SimpleTestCase):
    def setUp(self) -> None:
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)

    def test_rebuilds_keep_the_events_table_and_debounce_each_table_separately(self) -> None:
        team = Team(id=44, timezone="UTC")
        query = MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        with mock.patch(_DELAY) as delay, new_events_schema_for_request():
            for native in (False, True, False, True):
                with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=native)):
                    handle_not_ready(team=team, query=query)

        assert [call.kwargs["query"]["modifiers"]["useNewEventsSchema"] for call in delay.call_args_list] == [
            False,
            True,
        ]
        assert query.modifiers is None


class TestMarketingLazyPrecompute(BaseTest):
    def setUp(self):
        super().setUp()
        self.query = MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        redis.get_client().delete(self._debounce_key(self.query))
        redis.get_client().delete(f"ma_swr_reval_rate:{self.team.id}")
        reset_query_tags()

    def tearDown(self):
        reset_query_tags()
        super().tearDown()

    def _debounce_key(self, query: MarketingAnalyticsTableQuery) -> str:
        return f"ma_swr_reval:{self.team.id}:{_query_shape_key(_revalidation_query(team=self.team, query=query))}"

    @parameterized.expand(
        [
            # User-facing read: precompute-only. Never build inline (run_inserts=False), and serve stale
            # up to the ceiling so a warmer that has fallen behind still answers instead of going not-ready.
            ("user_facing", None, False),
            # The Dagster warmer, which tags CACHE_WARMUP. It is the producer, so it must build (default
            # run_inserts=True) and take no grace — served its own stale rows it would never recompute.
            ("dagster_warmer", {"feature": Feature.CACHE_WARMUP}, True),
            ("revalidation_task", {"trigger": REVALIDATION_TRIGGER, "feature": Feature.CACHE_WARMUP}, True),
            # Belt: should the feature tag ever be clobbered before the ensure (web hit exactly this),
            # the trigger alone must still classify the revalidation task as a refresher.
            ("revalidation_task_feature_clobbered", {"trigger": REVALIDATION_TRIGGER, "feature": Feature.QUERY}, True),
        ]
    )
    @mock.patch(f"{_MODULE}.ensure_precomputed")
    def test_read_serves_precompute_only_refresher_builds(self, _name, tags, is_refresher, mock_ensure):
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[])
        if tags is None:
            marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        else:
            with tags_context(**tags):
                marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)

        kwargs = mock_ensure.call_args.kwargs
        if is_refresher:
            # A refresher must not be forced read-only or served stale, or it would never rebuild.
            assert "run_inserts" not in kwargs, f"refresher {tags} must be allowed to build"
            assert "stale_while_revalidate_seconds" not in kwargs, f"refresher {tags} must not be served stale"
        else:
            assert kwargs["run_inserts"] is False, "user-facing read must never materialize inline"
            assert kwargs["stale_while_revalidate_seconds"] == PRECOMPUTE_ONLY_MAX_STALE_SECONDS

    @mock.patch(_DELAY)
    def test_handle_not_ready_enqueues_a_background_warm(self, delay):
        # A cold team outside the rolling warm set reads not-ready; that must trigger a one-off background
        # warm so its next visit is served. Without this, cold teams stay not-ready forever.
        handle_not_ready(team=self.team, query=self.query)

        assert delay.call_count == 1
        assert delay.call_args.kwargs["team_id"] == self.team.pk

    @mock.patch(_DELAY)
    def test_handle_stale_served_tags_read_and_debounces_same_shape(self, delay):
        # A dashboard renders several tiles off one query shape and they go stale together. Each stale
        # ensure must tag the read, but they must collapse to a single background rebuild.
        for _ in range(3):
            handle_stale_served(team=self.team, query=self.query)

        assert get_query_tag_value("precompute_stale") is True
        assert delay.call_count == 1
        payload = delay.call_args.kwargs
        assert payload["team_id"] == self.team.pk
        assert payload["query"]["kind"] == "MarketingAnalyticsTableQuery"

    @parameterized.expand(
        [
            # Paging or re-sorting a stale table is a normal interaction; each one must not buy its own
            # rebuild of the exact same windows.
            ("pagination", {"limit": 500, "offset": 100}, 1),
            ("sort", {"orderBy": [["cost", "DESC"]]}, 1),
            # `select` gates which conversion goals get built, and a different window is different data.
            ("select", {"select": ["campaign", "cost"]}, 2),
            ("date_range", {"dateRange": DateRange(date_from="-30d")}, 2),
            # Compare is stripped before revalidation (it drives a separate runner + window), so toggling
            # it collapses onto the same rebuild rather than buying a second one.
            ("compare_toggle", {"compareFilter": CompareFilter(compare=True)}, 1),
        ]
    )
    @mock.patch(_DELAY)
    def test_debounce_splits_only_on_precompute_identity(self, _name, overrides, expected_enqueues, delay):
        variant = self.query.model_copy(update=overrides)
        redis.get_client().delete(self._debounce_key(variant))

        handle_stale_served(team=self.team, query=self.query)
        handle_stale_served(team=self.team, query=variant)

        assert delay.call_count == expected_enqueues

    @mock.patch(_DELAY)
    def test_distinct_shapes_are_capped_by_the_team_warm_budget(self, delay):
        # Each date range gets its own debounce slot, so a flood of cold shapes must still stop at the
        # team's budget instead of queueing one long rebuild per shape.
        shapes = [
            self.query.model_copy(update={"dateRange": DateRange(date_from=f"-{days}d")})
            for days in range(1, TEAM_WARM_BUDGET.burst + 4)
        ]
        for shape in shapes:
            redis.get_client().delete(self._debounce_key(shape))
            handle_not_ready(team=self.team, query=shape)

        assert delay.call_count == TEAM_WARM_BUDGET.burst
        throttled_key = self._debounce_key(shapes[-1])
        assert 0 < redis.get_client().ttl(throttled_key) <= ENQUEUE_FAILURE_BACKOFF_SECONDS

    @mock.patch(_DELAY)
    @mock.patch(f"{_MODULE}.redis.get_client", side_effect=Exception("redis down"))
    def test_enqueue_failure_still_serves_the_stale_read(self, _redis, delay):
        # The enqueue runs on the user-facing read path. A Redis or broker outage must degrade to
        # "serve stale, warmer converges" — never raise into the read and force the slow live fallback.
        handle_stale_served(team=self.team, query=self.query)

        assert delay.call_count == 0
        assert get_query_tag_value("precompute_stale") is True

    @mock.patch(_DELAY, side_effect=Exception("broker down"))
    def test_broker_failure_shrinks_the_debounce_slot_to_a_backoff(self, _delay):
        # The slot is claimed before the enqueue is confirmed. If the enqueue fails, holding it the full
        # window would suppress every retry for 10 minutes with no rebuild in flight — release it to a
        # short backoff so revalidation resumes soon after the broker recovers.
        key = self._debounce_key(self.query)

        handle_stale_served(team=self.team, query=self.query)

        assert 0 < redis.get_client().ttl(key) <= ENQUEUE_FAILURE_BACKOFF_SECONDS

    @mock.patch(_DELAY)
    def test_compare_is_stripped_from_the_revalidation_query(self, delay):
        # A compare read runs a separate previous-period runner that revalidates its own window; leaving
        # compare on would make the task re-derive a second, un-requested comparison window.
        query = self.query.model_copy(update={"compareFilter": CompareFilter(compare=True)})

        handle_stale_served(team=self.team, query=query)

        assert "compareFilter" not in delay.call_args.kwargs["query"]
