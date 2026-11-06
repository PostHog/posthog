import datetime as dt

from posthog.schema import DateRange, TraceSpansQuery

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.impact_query_runner import TraceSpansImpactQueryRunner, run_impact_query
from products.tracing.backend.logic import run_aggregation_query
from products.tracing.backend.models import TeamTracingConfig, TracingIdentityAttributeKeys
from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# (service, span attributes, resource attributes). Span-attribute keys carry the ingestion MV's
# `__str` suffix; resource-attribute keys do not.
SPANS = [
    ("checkout", {"sessionId__str": "sess-a", "posthogDistinctId__str": "user-1"}, {}),
    ("checkout", {"sessionId__str": "sess-a", "posthogDistinctId__str": "user-1"}, {}),
    ("checkout", {"sessionId__str": "sess-b", "posthogDistinctId__str": "user-2"}, {}),
    ("checkout", {}, {"sessionId": "sess-c", "posthogDistinctId": "user-3"}),
    ("checkout", {"sessionId__str": "sess-d"}, {"sessionId": "sess-ignored"}),
    ("checkout", {"my.session.key__str": "sess-custom"}, {}),
    ("worker", {}, {}),
    ("worker", {}, {}),
]

TOTAL_SPANS = len(SPANS)
SPANS_WITH_SESSION = 5
SPANS_WITH_DISTINCT_ID = 4
UNIQUE_SESSIONS = 4
UNIQUE_USERS = 3


def _map_literal(entries: dict[str, str]) -> str:
    if not entries:
        return "map()"
    pairs = ", ".join(f"'{key}', '{value}'" for key, value in entries.items())
    return f"map({pairs})"


class _ImpactTestBase(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_str = (base + dt.timedelta(milliseconds=100)).strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for i, (service, attributes, resource_attributes) in enumerate(SPANS):
            trace_id = _b64(i.to_bytes(16, "big"))
            span_id = _b64((2000 + i).to_bytes(8, "big"))
            rows.append(
                f"('019e8770-0000-0000-0000-{i:012d}', {cls.team.id}, '{trace_id}', '{span_id}', '', "
                f"'POST /checkout', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, '{service}', "
                f"{_map_literal(attributes)}, {_map_literal(resource_attributes)})"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    def _impact(self, **kwargs) -> dict:
        response = run_impact_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            **kwargs,
        )
        assert isinstance(response.results, dict)
        return response.results


class TestTraceSpansImpact(_ImpactTestBase):
    def test_impact_counts(self):
        impact = self._impact()
        self.assertEqual(
            {key: impact[key] for key in ("total", "spansWithSessionId", "spansWithDistinctId", "sessions", "users")},
            {
                "total": TOTAL_SPANS,
                "spansWithSessionId": SPANS_WITH_SESSION,
                "spansWithDistinctId": SPANS_WITH_DISTINCT_ID,
                "sessions": UNIQUE_SESSIONS,
                "users": UNIQUE_USERS,
            },
        )

    def test_span_attribute_wins_over_resource_attribute(self):
        values = {entry["value"] for entry in self._impact()["topSessions"]}
        self.assertIn("sess-d", values)
        self.assertNotIn("sess-ignored", values)

    def test_top_sessions_ordered_by_span_count(self):
        top_sessions = self._impact()["topSessions"]
        self.assertEqual(top_sessions[0]["value"], "sess-a")
        self.assertEqual(top_sessions[0]["count"], 2)

    def test_filters_narrow_the_counts(self):
        impact = self._impact(service_names=["worker"])
        self.assertEqual(impact["total"], 2)
        self.assertEqual(impact["sessions"], 0)
        self.assertEqual(impact["topSessions"], [])

    def test_unconfigured_key_reads_as_no_identity(self):
        self.assertNotIn("sess-custom", {entry["value"] for entry in self._impact()["topSessions"]})

    def test_cache_key_covers_the_configured_identity_keys(self):
        # The keys come from Postgres, not the query, so nothing else in the cache payload moves
        # when a team edits them. Without them a config change keeps serving the old counts.
        def cache_key(session_keys: list[str]) -> str:
            runner = TraceSpansImpactQueryRunner(
                TraceSpansQuery(dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO)),
                self.team,
                identity_keys=TracingIdentityAttributeKeys(session=session_keys, distinct_id=["posthogDistinctId"]),
            )
            return runner.get_cache_key()

        self.assertNotEqual(cache_key(["sessionId"]), cache_key(["my.session.key"]))

    def test_configured_keys_are_read(self):
        TeamTracingConfig.objects.update_or_create(
            team=self.team, defaults={"tracing_session_id_attribute_keys": ["my.session.key"]}
        )

        impact = self._impact()
        self.assertEqual(impact["sessions"], UNIQUE_SESSIONS + 1)
        self.assertEqual(impact["spansWithSessionId"], SPANS_WITH_SESSION + 1)
        self.assertIn("sess-a", {entry["value"] for entry in impact["topSessions"]})


class TestOperationsImpactColumns(_ImpactTestBase):
    def _rows(self, include_impact: bool) -> dict:
        response = run_aggregation_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            include_impact=include_impact,
        )
        return {row.service_name: row for row in response.results}

    def test_impact_columns(self):
        # The runner unpacks these rows positionally.
        rows = self._rows(include_impact=True)
        checkout = rows["checkout"]
        self.assertEqual(
            (checkout.sessions, checkout.users, checkout.spans_with_session_id, checkout.spans_with_distinct_id),
            (UNIQUE_SESSIONS, UNIQUE_USERS, SPANS_WITH_SESSION, SPANS_WITH_DISTINCT_ID),
        )
        self.assertEqual(rows["worker"].sessions, 0)

    def test_impact_columns_absent_by_default(self):
        # None rather than 0 is what proves the default path never read the attribute maps.
        row = self._rows(include_impact=False)["checkout"]
        self.assertIsNone(row.sessions)
        self.assertIsNone(row.users)
        self.assertIsNone(row.spans_with_session_id)
        self.assertIsNone(row.spans_with_distinct_id)

    def test_durations_survive_the_extra_columns(self):
        with_impact = self._rows(include_impact=True)["checkout"]
        without_impact = self._rows(include_impact=False)["checkout"]
        self.assertEqual(with_impact.count, without_impact.count)
        self.assertEqual(with_impact.p95_duration_nano, without_impact.p95_duration_nano)
