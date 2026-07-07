import uuid
from datetime import date, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    IntervalType,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTrendsMetric,
    MarketingAnalyticsTrendsQuery,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.marketing_costs_sql import DISTRIBUTED_MARKETING_COSTS_TABLE

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_trends_query_runner import (
    MarketingAnalyticsTrendsQueryRunner,
)

_INSERT_COLUMNS = (
    "team_id, job_id, source_id, source_name, grain, match_key, campaign_id, campaign_name, "
    "ad_group_id, ad_group_name, ad_id, ad_name, cost_date, cost, clicks, impressions, "
    "reported_conversions, reported_conversion_value, computed_at, expires_at"
)


@override_settings(IN_UNIT_TESTING=True)
class TestMarketingAnalyticsTrendsQueryRunner(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _insert_cell(
        self,
        *,
        job_id: str,
        source_name: str,
        campaign_id: str,
        cost_date: date,
        computed_at: datetime,
        clicks: float = 0.0,
        cost: float = 0.0,
        reported_conversions: float = 0.0,
        reported_conversion_value: float = 0.0,
    ) -> None:
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_MARKETING_COSTS_TABLE()} ({_INSERT_COLUMNS}) VALUES",
            [
                (
                    self.team.pk,
                    job_id,
                    f"{source_name}_test",
                    source_name,
                    "campaign",
                    campaign_id,
                    campaign_id,
                    campaign_id,
                    "",
                    "",
                    "",
                    "",
                    cost_date,
                    cost,
                    clicks,
                    0.0,
                    reported_conversions,
                    reported_conversion_value,
                    computed_at,
                    date(2099, 1, 1),
                )
            ],
        )

    def _run(self, *, metric: MarketingAnalyticsTrendsMetric, date_range: DateRange, job_ids: list[str]) -> list[dict]:
        runner = MarketingAnalyticsTrendsQueryRunner(
            query=MarketingAnalyticsTrendsQuery(
                metric=metric,
                interval=IntervalType.MONTH,
                dateRange=date_range,
                properties=[],
            ),
            team=self.team,
        )
        with patch.object(
            MarketingAnalyticsTrendsQueryRunner,
            "_resolve_precompute_cost_jobs",
            lambda self, dr: (MarketingAnalyticsDrillDownLevel.CAMPAIGN, job_ids, [], None),
        ):
            return runner._calculate().results  # type: ignore[return-value]

    @parameterized.expand(
        [
            (MarketingAnalyticsTrendsMetric.CLICKS, "clicks", 100.0, 150.0),
            (MarketingAnalyticsTrendsMetric.COST, "cost", 100.0, 150.0),
        ]
    )
    def test_trends_series_takes_latest_job_per_cell_not_sum(self, metric, field, stale_value, matured_value):
        # Same (campaign, day) cell under two job_ids — a stale value and a matured one. job_id is in the
        # ReplacingMergeTree sort key so both rows survive; the bucketed time series must roll up the
        # latest-computed value (argMax), not the sum, or the chart double-counts like the raw TrendsQuery.
        job_old, job_new = str(uuid.uuid4()), str(uuid.uuid4())
        self._insert_cell(
            job_id=job_old,
            source_name="google",
            campaign_id="c1",
            cost_date=date(2023, 1, 15),
            computed_at=datetime(2023, 1, 15, 10, 0),
            **{field: stale_value},
        )
        self._insert_cell(
            job_id=job_new,
            source_name="google",
            campaign_id="c1",
            cost_date=date(2023, 1, 15),
            computed_at=datetime(2023, 1, 16, 10, 0),
            **{field: matured_value},
        )

        results = self._run(
            metric=metric,
            date_range=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            job_ids=[job_old, job_new],
        )

        assert len(results) == 1, f"expected a single 'google' series, got {[r['label'] for r in results]}"
        series_total = sum(float(v) for v in results[0]["data"])
        assert series_total == matured_value, (
            f"expected latest-job {field} {matured_value} (argMax), got {series_total} (sum would be {stale_value + matured_value})"
        )

    def test_trends_buckets_by_interval_and_breaks_down_by_source(self):
        # Two sources across two months: the runner must emit one series per source, each bucketed by
        # interval — not a single flattened total.
        job = str(uuid.uuid4())
        self._insert_cell(
            job_id=job,
            source_name="google",
            campaign_id="c1",
            cost_date=date(2023, 1, 10),
            computed_at=datetime(2023, 1, 11, 10, 0),
            clicks=100.0,
        )
        self._insert_cell(
            job_id=job,
            source_name="google",
            campaign_id="c1",
            cost_date=date(2023, 2, 10),
            computed_at=datetime(2023, 2, 11, 10, 0),
            clicks=40.0,
        )
        self._insert_cell(
            job_id=job,
            source_name="bing",
            campaign_id="c2",
            cost_date=date(2023, 1, 20),
            computed_at=datetime(2023, 1, 21, 10, 0),
            clicks=25.0,
        )

        results = self._run(
            metric=MarketingAnalyticsTrendsMetric.CLICKS,
            date_range=DateRange(date_from="2023-01-01", date_to="2023-02-28"),
            job_ids=[job],
        )

        by_source = {r["label"]: [float(v) for v in r["data"]] for r in results}
        assert set(by_source) == {"google", "bing"}
        # Two monthly buckets (Jan, Feb) in range → each series has two data points.
        assert all(len(data) == 2 for data in by_source.values())
        assert sum(by_source["google"]) == 140.0  # 100 (Jan) + 40 (Feb)
        assert sum(by_source["bing"]) == 25.0  # Jan only
