from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsTableQuery

from posthog import redis
from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags, tags_context

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import (
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

    @mock.patch(_DELAY)
    @mock.patch(f"{_MODULE}.redis.get_client", side_effect=Exception("redis down"))
    def test_enqueue_failure_still_serves_the_stale_read(self, _redis, delay):
        # The enqueue runs on the user-facing read path. A Redis or broker outage must degrade to
        # "serve stale, warmer converges" — never raise into the read and force the slow live fallback.
        handle_stale_served(team=self.team, query=self.query)

        assert delay.call_count == 0
        assert get_query_tag_value("precompute_stale") is True
