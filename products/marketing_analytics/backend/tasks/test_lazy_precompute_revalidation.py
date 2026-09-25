from posthog.test.base import BaseTest
from unittest import mock

from posthog.schema import DateRange, MarketingAnalyticsTableQuery

from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags

from products.analytics_platform.backend.lazy_computation.stale_policy import is_background_warming_request
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import BACKGROUND_WARMING_TRIGGERS
from products.marketing_analytics.backend.tasks.lazy_precompute_revalidation import (
    revalidate_marketing_analytics_precompute,
)

_MODULE = "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation"


class TestMarketingLazyPrecomputeRevalidation(BaseTest):
    def setUp(self):
        super().setUp()
        self.query = MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[]).model_dump(
            mode="json", exclude_none=True
        )
        reset_query_tags()

    def tearDown(self):
        reset_query_tags()
        super().tearDown()

    @mock.patch(f"{_MODULE}.get_query_runner")
    def test_materializes_precomputes_as_a_refresher_without_executing(self, get_runner):
        # The tags must already be set while the runner is built, since its construction-time ensures read
        # them. Classified as a refresher it gets no serve-stale grace — served its own stale rows it would
        # never recompute and marketing data would stop refreshing.
        # It must build (to_query) but NOT execute (run): a full run of this userless, access-control-
        # bypassed runner would write an all-sources response into the shared per-team result cache, which
        # a warehouse-restricted user could then read.
        tags_at_build: dict[str, object] = {}
        runner = mock.MagicMock()

        def capture(**_kwargs):
            tags_at_build["refresher"] = is_background_warming_request(BACKGROUND_WARMING_TRIGGERS)
            tags_at_build["feature"] = get_query_tag_value("feature")
            return runner

        get_runner.side_effect = capture

        revalidate_marketing_analytics_precompute(team_id=self.team.pk, query=self.query)

        # CACHE_WARMUP would route the INSERTs to the read-only cache_warmup ClickHouse user.
        assert tags_at_build == {"refresher": True, "feature": Feature.PREAGGREGATION}
        runner.to_query.assert_called_once_with()
        runner.run.assert_not_called()

    @mock.patch(f"{_MODULE}.get_query_runner")
    def test_deleted_team_does_not_raise_into_the_worker(self, get_runner):
        revalidate_marketing_analytics_precompute(team_id=self.team.pk + 10_000, query=self.query)

        assert get_runner.call_count == 0

    @mock.patch(f"{_MODULE}.get_query_runner", side_effect=Exception("clickhouse down"))
    def test_query_failure_is_swallowed(self, _get_runner):
        # Best-effort by design: the next stale hit re-enqueues and the warmer converges, so a failure here
        # must not surface as a task error.
        revalidate_marketing_analytics_precompute(team_id=self.team.pk, query=self.query)
