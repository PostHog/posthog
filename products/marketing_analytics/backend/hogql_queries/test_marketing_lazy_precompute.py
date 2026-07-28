from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import CompareFilter, DateRange, MarketingAnalyticsTableQuery

from posthog import redis
from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags, tags_context

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import (
    ENQUEUE_FAILURE_BACKOFF_SECONDS,
    REVALIDATION_TRIGGER,
    STALE_WHILE_REVALIDATE_SECONDS,
    _query_shape_key,
    handle_stale_served,
    marketing_ensure_precomputed,
)

_MODULE = "products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute"
_DELAY = (
    "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation"
    ".revalidate_marketing_analytics_precompute.delay"
)


class TestMarketingLazyPrecompute(BaseTest):
    def setUp(self):
        super().setUp()
        self.query = MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        redis.get_client().delete(f"ma_swr_reval:{self.team.id}:{_query_shape_key(self.query)}")
        reset_query_tags()
        # Flag on by default here; the flag's own behaviour is covered by test_flag_gates_serve_stale.
        # Cached on the team instance, so it must be cleared between cases that mock it differently.
        self.team._ma_serve_stale_flag = True  # type: ignore[attr-defined]

    def tearDown(self):
        reset_query_tags()
        super().tearDown()

    @parameterized.expand(
        [
            ("user_facing", None),
            # The Dagster warmer, which tags CACHE_WARMUP. Served its own stale rows it would persist
            # them as fresh and never rebuild, and marketing data would stop refreshing entirely.
            ("dagster_warmer", {"feature": Feature.CACHE_WARMUP}),
            ("revalidation_task", {"trigger": REVALIDATION_TRIGGER, "feature": Feature.CACHE_WARMUP}),
            # Belt: should the feature tag ever be clobbered before the ensure (web hit exactly this),
            # the trigger alone must still classify the revalidation task as a refresher.
            ("revalidation_task_feature_clobbered", {"trigger": REVALIDATION_TRIGGER, "feature": Feature.QUERY}),
        ]
    )
    @mock.patch(f"{_MODULE}.ensure_precomputed")
    def test_serve_stale_grace_by_caller(self, _name, tags, mock_ensure):
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[])
        if tags is None:
            marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        else:
            with tags_context(**tags):
                marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)

        grace = mock_ensure.call_args.kwargs["stale_while_revalidate_seconds"]
        if tags is None:
            assert grace == STALE_WHILE_REVALIDATE_SECONDS
        else:
            assert grace is None, f"refresher {tags} must not be served stale"

    @parameterized.expand([("flag_on", True, STALE_WHILE_REVALIDATE_SECONDS), ("flag_off", False, None)])
    @mock.patch(f"{_MODULE}.ensure_precomputed")
    @mock.patch(f"{_MODULE}.feature_enabled_or_false")
    def test_flag_gates_serve_stale(self, _name, flag, expected_grace, flag_eval, mock_ensure):
        # The kill switch. Off must hand the executor no grace at all, so the read materializes inline
        # exactly as it did before serve-stale existed (and, getting no `stale`, enqueues no revalidation).
        del self.team._ma_serve_stale_flag  # type: ignore[attr-defined]
        flag_eval.return_value = flag
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[])

        marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)

        assert mock_ensure.call_args.kwargs["stale_while_revalidate_seconds"] == expected_grace

    @mock.patch(f"{_MODULE}.ensure_precomputed")
    @mock.patch(f"{_MODULE}.feature_enabled_or_false")
    def test_flag_is_evaluated_once_per_team_across_the_reads_ensures(self, flag_eval, mock_ensure):
        # One load fires this several times (touchpoints, per-goal conversions, costs); each evaluation
        # would otherwise be a flag call plus a $feature_flag_called event on the read path.
        del self.team._ma_serve_stale_flag  # type: ignore[attr-defined]
        flag_eval.return_value = True
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[])

        for _ in range(4):
            marketing_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)

        assert flag_eval.call_count == 1

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
        redis.get_client().delete(f"ma_swr_reval:{self.team.id}:{_query_shape_key(variant)}")

        handle_stale_served(team=self.team, query=self.query)
        handle_stale_served(team=self.team, query=variant)

        assert delay.call_count == expected_enqueues

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
        key = f"ma_swr_reval:{self.team.id}:{_query_shape_key(self.query)}"

        handle_stale_served(team=self.team, query=self.query)

        assert 0 < redis.get_client().ttl(key) <= ENQUEUE_FAILURE_BACKOFF_SECONDS

    @mock.patch(_DELAY)
    def test_compare_is_stripped_from_the_revalidation_query(self, delay):
        # A compare read runs a separate previous-period runner that revalidates its own window; leaving
        # compare on would make the task re-derive a second, un-requested comparison window.
        query = self.query.model_copy(update={"compareFilter": CompareFilter(compare=True)})

        handle_stale_served(team=self.team, query=query)

        assert "compareFilter" not in delay.call_args.kwargs["query"]
