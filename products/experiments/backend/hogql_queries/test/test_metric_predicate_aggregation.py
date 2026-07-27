from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import DateRange, EventPropertyFilter, EventsNode, ExperimentMetricMathType, HogQLPropertyFilter

from posthog.hogql.errors import ExposedHogQLError

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.experiments.backend.hogql_queries.experiment_metric_values import build_metric_predicate

AGGREGATE_HOGQL = (
    "avg(arrayUniq(arrayMap(x -> JSONExtractInt(x, 'category_id'), JSONExtractArrayRaw(properties.products))))"
)


class TestMetricPredicateAggregation(BaseTest):
    def _date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=DateRange(date_from="2024-01-01", date_to="2024-02-01", explicitDate=True),
            team=self.team,
            interval=None,
            now=timezone.now(),
        )

    @parameterized.expand(
        [
            ("avg", AGGREGATE_HOGQL),
            ("count", "count()"),
        ]
    )
    def test_aggregate_in_metric_filter_raises_clear_error(self, _name, hogql_filter):
        # An aggregate in a metric filter would otherwise be emitted verbatim into the metric-event
        # WHERE and fail every load with ClickHouse's IllegalAggregation error.
        source = EventsNode(event="purchase", properties=[HogQLPropertyFilter(key=hogql_filter)])

        with self.assertRaises(ExposedHogQLError) as ctx:
            build_metric_predicate(
                team=self.team,
                source=source,
                date_range_query=self._date_range(),
                conversion_window_seconds=0,
            )

        self.assertIn("aggregate function", str(ctx.exception))

    @parameterized.expand(
        [
            # A HogQL-math aggregate is a metric value rather than a filter, and its inner
            # expression is extracted elsewhere, so it must not trip the filter guard.
            (
                "hogql_math_aggregate_value",
                EventsNode(event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql=AGGREGATE_HOGQL),
            ),
            (
                "non_aggregate_property_filter",
                EventsNode(
                    event="purchase", properties=[EventPropertyFilter(key="country", value="US", operator="exact")]
                ),
            ),
        ]
    )
    def test_valid_metric_source_builds_predicate(self, _name, source):
        predicate = build_metric_predicate(
            team=self.team,
            source=source,
            date_range_query=self._date_range(),
            conversion_window_seconds=0,
        )

        self.assertIsNotNone(predicate)
