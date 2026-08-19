from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    DateRange,
    QueryLogTags,
    RetentionEntity,
    RetentionFilter,
    RetentionPeriod,
    RetentionQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, reset_query_tags, tag_queries
from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_retention import WebRetentionQueryRunner
from products.web_analytics.backend.hogql_queries.web_retention_lazy_precompute import retention_precompute_servable


def _retention_query(**overrides: Any) -> RetentionQuery:
    filter_kwargs: dict[str, Any] = {
        "retentionType": "retention_first_time",
        "retentionReference": "total",
        "totalIntervals": 4,
        "period": RetentionPeriod.WEEK,
    }
    filter_kwargs.update(overrides.pop("filter_overrides", {}))
    retention_filter = RetentionFilter(**filter_kwargs)
    return RetentionQuery(
        dateRange=DateRange(date_from="2024-01-07", date_to="2024-02-03"),
        properties=[],
        filterTestAccounts=False,
        retentionFilter=retention_filter,
        tags=QueryLogTags(productKey="web_analytics"),
        **overrides,
    )


class TestRetentionPrecomputeGate(APIBaseTest):
    def test_web_analytics_tile_shape_is_servable(self) -> None:
        assert retention_precompute_servable(_retention_query()) is True

    @parameterized.expand(
        [
            ("day_period", {"filter_overrides": {"period": RetentionPeriod.DAY}}),
            ("recurring_type", {"filter_overrides": {"retentionType": "retention_recurring"}}),
            ("custom_brackets", {"filter_overrides": {"retentionCustomBrackets": [1, 2]}}),
            ("cumulative", {"filter_overrides": {"cumulative": True}}),
            ("minimum_occurrences", {"filter_overrides": {"minimumOccurrences": 2}}),
            (
                "specific_target_entity",
                {"filter_overrides": {"targetEntity": RetentionEntity(id="$pageview", type="events")}},
            ),
            (
                "breakdown",
                {"breakdownFilter": BreakdownFilter(breakdowns=[Breakdown(property="$browser", type="event")])},
            ),
            ("sampling", {"samplingFactor": 0.1}),
        ]
    )
    def test_non_tile_shapes_fall_back(self, _name: str, overrides: dict[str, Any]) -> None:
        assert retention_precompute_servable(_retention_query(**overrides)) is False


@override_settings(IN_UNIT_TESTING=True)
class TestWebRetentionLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_retention_preaggregated")

    @contextmanager
    def _enable(self) -> Iterator[None]:
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
                    return_value=True,
                )
            )
            stack.enter_context(
                patch(
                    "products.web_analytics.backend.hogql_queries.web_retention_lazy_precompute.posthoganalytics.feature_enabled",
                    return_value=True,
                )
            )
            yield

    def _seed(self) -> None:
        # Weeks are Sunday-aligned (default week start). Range covers
        # W0=Jan 7, W1=Jan 14, W2=Jan 21, W3=Jan 28.
        # p1: first event in W0, returns W1 and W3 — a full cohort row.
        # p2: first event in W1, returns W2 — a second cohort.
        # p3: first event BEFORE the range (Dec 1), active in W0 and W2 —
        #     must appear in no cohort at all (first occurrence outside range).
        for pid in ("p1", "p2", "p3"):
            _create_person(team_id=self.team.pk, distinct_ids=[pid], properties={})
        events = [
            ("p1", "2024-01-08T10:00:00Z"),
            ("p1", "2024-01-15T10:00:00Z"),
            ("p1", "2024-01-30T10:00:00Z"),
            ("p2", "2024-01-16T09:00:00Z"),
            ("p2", "2024-01-22T09:00:00Z"),
            ("p3", "2023-12-01T12:00:00Z"),
            ("p3", "2024-01-09T12:00:00Z"),
            ("p3", "2024-01-23T12:00:00Z"),
        ]
        for pid, ts in events:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=pid,
                timestamp=ts,
                properties={"$host": "example.com"},
            )

    def _warm(self, query: RetentionQuery) -> None:
        # Mimic the SWR revalidation task: under a warming trigger the ensure
        # runs inserts inline instead of check-only, building the buckets a
        # plain user read can then be served from.
        tag_queries(
            team_id=self.team.pk,
            trigger="webAnalyticsStaleRevalidation",
            feature=Feature.CACHE_WARMUP,
            product=Product.WEB_ANALYTICS,
        )
        try:
            WebRetentionQueryRunner(team=self.team, query=query).calculate()
        finally:
            reset_query_tags()

    @freeze_time("2024-02-10T12:00:00Z")
    def test_precomputed_matches_live_retention(self) -> None:
        self._seed()
        query = _retention_query()

        live = RetentionQueryRunner(team=self.team, query=query).calculate()

        with self._enable():
            self._warm(query)
            precomputed = WebRetentionQueryRunner(team=self.team, query=query).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0
        # The live path stamps printed HogQL on the response; the bucket path
        # never does. A None here proves the serve did not silently fall back.
        assert precomputed.hogql is None
        assert live.hogql is not None
        assert len(precomputed.results) == len(live.results)

        def _row(row: Any) -> tuple[Any, Any, list[Any]]:
            if isinstance(row, dict):
                return row["date"], row["label"], [v["count"] for v in row["values"]]
            return row.date, row.label, [v.count for v in row.values]

        for live_row, pre_row in zip(live.results, precomputed.results):
            live_date, live_label, live_counts = _row(live_row)
            pre_date, pre_label, pre_counts = _row(pre_row)
            assert pre_date == live_date
            assert pre_label == live_label
            assert pre_counts == live_counts, (live_label, live_counts, pre_counts)

    @freeze_time("2024-02-10T12:00:00Z")
    def test_dispatch_routes_only_when_flag_enabled(self) -> None:
        query = _retention_query().model_dump(mode="json")

        runner = get_query_runner(query, self.team)
        assert isinstance(runner, RetentionQueryRunner)
        assert not isinstance(runner, WebRetentionQueryRunner)

        with patch(
            "products.web_analytics.backend.hogql_queries.web_retention_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            runner = get_query_runner(query, self.team)
        assert isinstance(runner, WebRetentionQueryRunner)

    @freeze_time("2024-02-10T12:00:00Z")
    def test_check_miss_enqueues_the_retention_query_for_revalidation(self) -> None:
        # The revalidation task replays whatever query the miss enqueued; only
        # replaying the RetentionQuery rebuilds this family. Enqueuing the
        # inner overview carrier instead would warm web_overview forever while
        # retention misses never converge.
        self._seed()
        with (
            self._enable(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.enqueue_stale_revalidation"
            ) as mock_enqueue,
        ):
            response = WebRetentionQueryRunner(team=self.team, query=_retention_query()).calculate()
        assert response.hogql is not None  # cold read fell back to live
        assert mock_enqueue.call_count >= 1
        enqueued_query = mock_enqueue.call_args.kwargs["query"]
        assert enqueued_query.kind == "RetentionQuery"
        assert mock_enqueue.call_args.kwargs["family"] == "web_retention"

    def test_cache_payload_carries_flag_state_as_kill_switch(self) -> None:
        runner = WebRetentionQueryRunner(team=self.team, query=_retention_query())
        assert runner.get_cache_payload()["web_retention_precompute"] is False
        with self._enable():
            assert runner.get_cache_payload()["web_retention_precompute"] is True
