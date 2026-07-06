import base64

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import run_service_names_query

SERVICE_NAME = "checkout-api"
# 02:00 UTC is still 2026-06-01 in US/Pacific (UTC-7 in June), so time_bucket = toStartOfDay(UTC) = 2026-06-02
# while the team-local day is 2026-06-01. A day filter printed in the team timezone would land on the wrong day.
SPAN_TS = "2026-06-02 02:00:00.000000"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestTraceServiceNames(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.team.timezone = "US/Pacific"
        cls.team.save()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        trace_id = _b64((1).to_bytes(16, "big"))
        span_id = _b64((1).to_bytes(8, "big"))
        row = (
            "("
            f"'019e8754-0000-0000-0000-000000000001', {cls.team.id}, '{trace_id}', '{span_id}', '', "
            f"'root', 2, '{SPAN_TS}', '{SPAN_TS}', '{SPAN_TS}', 0, '{SERVICE_NAME}'"
            ")"
        )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + row
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def test_short_window_returns_services_for_non_utc_team(self):
        # A ~2h window covering the span. On a non-UTC team this must not be shifted onto the
        # previous UTC day by the day-bucket bound, which would silently return an empty list.
        results = run_service_names_query(
            team=self.team,
            date_range=DateRange(date_from="2026-06-02T01:00:00Z", date_to="2026-06-02T03:00:00Z"),
        )
        self.assertEqual(results, [{"name": SERVICE_NAME}])
