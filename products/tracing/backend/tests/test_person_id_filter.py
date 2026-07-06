import base64
import datetime as dt
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, HogQLFilters, TraceSpansQuery

from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL
from posthog.models import Team
from posthog.test.persons import create_person

from products.tracing.backend.logic import TraceSpansQueryRunner
from products.tracing.backend.models import TeamTracingConfig

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestTracingPersonIdFilter(ClickhouseTestMixin, APIBaseTest):
    # `personId` on the span queries is expanded server-side to the person's distinct ids.
    # Person pages cap how many distinct ids they load client-side, so a client-built
    # distinct-id filter silently misses spans for id-heavy persons — the bug this class
    # guards against. Tests share one ClickHouse table; each uses unique distinct-id
    # values for isolation.

    CLASS_DATA_LEVEL_SETUP = True
    _span_counter = 0

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _insert_span(self, distinct_id_value: str, attribute_key: str = "posthogDistinctId") -> None:
        type(self)._span_counter += 1
        n = self._span_counter
        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_str = (base + dt.timedelta(milliseconds=5)).strftime("%Y-%m-%d %H:%M:%S.%f")
        # Keys in attributes_map_str carry the __str type suffix; the `attributes` ALIAS strips it.
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES "
            "("
            f"'{uuid4()}', {self.team.id}, '{_b64(n.to_bytes(16, 'big'))}', "
            f"'{_b64(n.to_bytes(8, 'big'))}', '', 'span.for.{distinct_id_value}', 2, "
            f"'{ts_str}', '{end_str}', '{ts_str}', 0, 'person-id-test-svc', "
            f"map('{attribute_key}__str', '{distinct_id_value}'), "
            "map('service.version', '1.2.3'))"
        )

    def _query_body(self, person_id: str) -> dict:
        return {
            "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
            "personId": person_id,
        }

    def _run_query(self, person_id: str) -> list[dict]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/query/",
            {"query": self._query_body(person_id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()["results"]

    def test_person_id_expands_to_all_distinct_ids(self):
        person = create_person(team=self.team, distinct_ids=["span-person-a1", "span-person-a2"])
        create_person(team=self.team, distinct_ids=["span-person-other"])
        self._insert_span("span-person-a1")
        self._insert_span("span-person-a2")
        self._insert_span("span-person-other")

        results = self._run_query(str(person.uuid))

        self.assertEqual(
            sorted(r["attributes"]["posthogDistinctId"] for r in results),
            ["span-person-a1", "span-person-a2"],
        )

    @parameterized.expand([("unknown_person",), ("person_from_another_team",)])
    def test_person_id_without_matching_person_matches_nothing(self, case: str):
        # An empty distinct-id list must never reach property_to_expr: it treats an empty
        # value list as always-true, which would leak every span in the project onto the tab.
        self._insert_span("span-person-leak")
        if case == "unknown_person":
            person_id = str(uuid4())
        else:
            other_team = Team.objects.create(organization=self.organization)
            person_id = str(create_person(team=other_team, distinct_ids=["span-person-leak"]).uuid)

        self.assertEqual(self._run_query(person_id), [])

    def test_person_id_respects_configured_attribute_key(self):
        TeamTracingConfig.objects.update_or_create(
            team=self.team, defaults={"tracing_distinct_id_attribute_key": "user.id"}
        )
        try:
            person = create_person(team=self.team, distinct_ids=["span-person-cfg"])
            self._insert_span("span-person-cfg", attribute_key="user.id")
            self._insert_span("span-person-cfg", attribute_key="posthogDistinctId")

            results = self._run_query(str(person.uuid))

            self.assertEqual([r["attributes"]["user.id"] for r in results], ["span-person-cfg"])
        finally:
            # CLASS_DATA_LEVEL_SETUP shares the team across tests; don't leak the override.
            TeamTracingConfig.objects.filter(team=self.team).delete()

    def test_person_id_filter_targets_string_attribute_map_for_numeric_ids(self):
        # All-numeric distinct ids must not route to the float attribute map — only the
        # string map is guaranteed to hold every attribute value.
        person = create_person(team=self.team, distinct_ids=["12345", "67890"])
        query = TraceSpansQuery(
            kind="TraceSpansQuery",
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            personId=str(person.uuid),
            limit=100,
        )
        runner = TraceSpansQueryRunner(query, self.team)
        executor = HogQLQueryExecutor(
            query_type="TraceSpansQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        self.assertIn("posthogDistinctId__str", query_str)
        self.assertNotIn("posthogDistinctId__float", query_str)
        self.assertIn("12345", query_str)
        self.assertIn("67890", query_str)

    def test_person_id_via_count_and_aggregate_apis(self):
        # count goes through the facade run_count_query (shared runner where()); aggregate
        # goes through _SpanAggregationMixin._where_without_date_range — a separate WHERE
        # assembly a dropped personId would silently un-scope.
        person = create_person(team=self.team, distinct_ids=["span-person-api"])
        self._insert_span("span-person-api")
        self._insert_span("span-person-api-unrelated")
        body = {"query": self._query_body(str(person.uuid))}

        count_response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/count/",
            body,
            format="json",
        )
        self.assertEqual(count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(count_response.json()["count"], 1)

        aggregate_response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/aggregate/",
            body,
            format="json",
        )
        self.assertEqual(aggregate_response.status_code, status.HTTP_200_OK)
        aggregate_rows = aggregate_response.json()["results"]
        self.assertEqual([row["name"] for row in aggregate_rows], ["span.for.span-person-api"])
