from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from posthog.schema import DateRange, HogQLQueryModifiers, WebOverviewQuery

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL

from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

PREAGG_MODIFIERS = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)


class TestWebOverviewSparkline(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            for distinct_id in ["d1_a", "d1_b", "d2_a"]:
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])

        # Day 1: two sessions, two visitors, three pageviews (one of them a single-page bounce)
        s1, s2 = str(uuid7("2024-01-01")), str(uuid7("2024-01-01"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1_a",
            timestamp="2024-01-01T10:00:00Z",
            properties={"$session_id": s1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1_a",
            timestamp="2024-01-01T10:05:00Z",
            properties={"$session_id": s1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1_b",
            timestamp="2024-01-01T11:00:00Z",
            properties={"$session_id": s2},
        )

        # Day 2: one session, one visitor, one pageview
        s3 = str(uuid7("2024-01-02"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d2_a",
            timestamp="2024-01-02T10:00:00Z",
            properties={"$session_id": s3},
        )

        flush_persons_and_events()
        self._populate_bounces_table()

    def _populate_bounces_table(self):
        select_sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-03", team_ids=[self.team.pk], select_only=True
        )
        sync_execute(f"INSERT INTO web_pre_aggregated_bounces\n{select_sql}")

    def _run(self, *, include_sparkline: bool, modifiers: HogQLQueryModifiers = PREAGG_MODIFIERS):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-03"),
            properties=[],
            compareFilter=None,
            includeSparkline=include_sparkline,
        )
        runner = WebOverviewQueryRunner(query=query, team=self.team, modifiers=modifiers)
        return {item.key: item for item in runner.calculate().results}

    def test_preaggregated_path_returns_per_day_series(self):
        items = self._run(include_sparkline=True)

        # Two day buckets in the range, oldest → newest.
        assert items["visitors"].series == [2, 1]
        assert items["views"].series == [3, 1]
        assert items["sessions"].series == [2, 1]
        # Bounce rate is surfaced as a percentage to match the headline value.
        assert items["bounce rate"].series == [50.0, 100.0]
        assert len(items["session duration"].series or []) == 2

    def test_no_series_when_sparkline_not_requested(self):
        items = self._run(include_sparkline=False)
        assert all(item.series is None for item in items.values())

    def test_no_series_when_preaggregated_tables_disabled(self):
        # Raw-events path: sparkline is precompute-only, so the frontend falls back to a trends query.
        items = self._run(
            include_sparkline=True, modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False)
        )
        assert all(item.series is None for item in items.values())
