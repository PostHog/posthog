import datetime as dt

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import (
    DashboardFilter,
    DateRange,
    MetricsQuery,
    MetricsQueryClause,
    MetricsQueryFilter,
    MetricsQueryGroupBy,
)

from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation
from products.metrics.backend.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.tests._seeder import seed_metric


class TestMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _runner(self, query: MetricsQuery) -> MetricsQueryRunner:
        return MetricsQueryRunner(query=query, team=self.team)

    def test_translates_schema_node_to_facade_request(self) -> None:
        query = MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a",
                    metricName="http_requests_total",
                    aggregation="histogram_quantile",
                    quantile=0.95,
                    filters=[MetricsQueryFilter(key="container", op="eq", value="capture", scope="attribute")],
                    groupBy=[MetricsQueryGroupBy(key="namespace")],
                )
            ],
            dateRange=DateRange(date_from="2026-07-01T00:00:00Z", date_to="2026-07-01T01:00:00Z"),
            interval="minute",
            formula=None,
        )

        request = self._runner(query)._to_request()

        clause = request.clauses[0]
        assert clause.metric_name == "http_requests_total"
        assert clause.aggregation is MetricAggregation.HISTOGRAM_QUANTILE
        assert clause.quantile == 0.95
        assert clause.filters[0].op is FilterOp.EQ
        assert clause.filters[0].scope is AttributeScope.ATTRIBUTE
        assert clause.group_by[0].scope is AttributeScope.AUTO
        assert request.interval == "minute"
        assert (request.date_to - request.date_from) == dt.timedelta(hours=1)

    @freeze_time("2026-07-01T12:00:00Z")
    def test_default_date_range_is_last_24_hours(self) -> None:
        query = MetricsQuery(
            clauses=[MetricsQueryClause(name="a", metricName="http_requests_total", aggregation="sum")]
        )

        request = self._runner(query)._to_request()

        assert (request.date_to - request.date_from) == dt.timedelta(hours=24)

    @freeze_time("2026-07-01T12:00:00Z")
    def test_calculate_returns_one_series_per_group(self) -> None:
        base = dt.datetime(2026, 7, 1, 11, 30, tzinfo=dt.UTC)
        for container, value in (("capture", 5.0), ("ingestion", 7.0)):
            seed_metric(
                team_id=self.team.pk,
                metric_name="queue_depth",
                metric_type="gauge",
                points=[(base + dt.timedelta(minutes=i), value) for i in range(3)],
                labels={"container": container},
            )

        query = MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a",
                    metricName="queue_depth",
                    aggregation="sum",
                    groupBy=[MetricsQueryGroupBy(key="container")],
                )
            ],
            dateRange=DateRange(date_from="2026-07-01T11:00:00Z", date_to="2026-07-01T12:00:00Z"),
        )

        response = self._runner(query).calculate()

        by_container = {series.labels.get("container"): series for series in response.results}
        assert set(by_container) == {"capture", "ingestion"}
        assert max(point.value for point in by_container["capture"].points) == 5.0
        assert max(point.value for point in by_container["ingestion"].points) == 7.0

    def test_generic_query_endpoint_accepts_metrics_query(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "MetricsQuery",
                    "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "sum"}],
                }
            },
        )

        assert response.status_code == 200, response.json()
        assert "results" in response.json()

    def test_dashboard_date_filters_override_query_date_range(self) -> None:
        query = MetricsQuery(
            clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")],
            dateRange=DateRange(date_from="-24h"),
        )
        runner = self._runner(query)

        runner.apply_dashboard_filters(DashboardFilter(date_from="-7d", date_to="-1d"))

        assert runner.query.dateRange is not None
        assert runner.query.dateRange.date_from == "-7d"
        assert runner.query.dateRange.date_to == "-1d"
