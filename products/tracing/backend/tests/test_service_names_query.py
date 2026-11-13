import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import run_service_names_query

# 03:30 UTC on June 2 is still June 1 in Los Angeles, so the team's local day trails the UTC day.
NOW = "2026-06-02T03:30:00Z"
SPAN_TS = "2026-06-02 03:20:00.000000"


class TestServiceNamesQuery(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.team.timezone = "America/Los_Angeles"
        cls.team.save()
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES "
            f"('019e8754-0000-0000-0000-000000000001', {cls.team.id}, 'AAAAAAAAAAAAAAAAAAAAAQ==', "
            f"'AAAAAAAAAAE=', '', 'root', 2, '{SPAN_TS}', '{SPAN_TS}', '{SPAN_TS}', 0, 'web')"
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    @parameterized.expand([("last_hour", "-1h"), ("last_day", "-24h")])
    @time_machine.travel(NOW, tick=False)
    def test_lists_recent_service_when_team_day_trails_utc_day(self, _name, date_from):
        results = run_service_names_query(team=self.team, date_range=DateRange(date_from=date_from))

        self.assertEqual(results, [{"name": "web"}])
