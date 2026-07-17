import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, LogsQuery

from posthog.hogql.errors import QueryError

from posthog.clickhouse.client import sync_execute

from products.logs.backend.column_expressions import canonical_key
from products.logs.backend.logs_query_runner import MAX_CUSTOM_COLUMNS, LogsQueryRunner

# The shipped fixture log is timestamped 2025-12-16, service_name "argo-rollouts",
# severity "info", with resource_attributes["k8s.container.name"] = "argo-rollouts-dashboard".
DATE_FROM = "2025-12-16T00:00:00Z"
DATE_TO = "2025-12-17T00:00:00Z"


class TestLogsCustomColumns(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        sync_execute("TRUNCATE TABLE IF EXISTS logs32")
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            log_item = json.loads(f.readline())
            log_item["team_id"] = cls.team.id
            sync_execute(f"INSERT INTO logs FORMAT JSONEachRow {json.dumps(log_item)}")

    @classmethod
    def tearDownClass(cls):
        sync_execute("TRUNCATE TABLE IF EXISTS logs32")
        super().tearDownClass()

    def _run(self, custom_columns: list[str]):
        query = LogsQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            serviceNames=["argo-rollouts"],
            severityLevels=[],
            filterGroup={"type": "AND", "values": []},
            customColumns=custom_columns,
        )
        return LogsQueryRunner(query, self.team).run()

    def test_custom_columns_resolve_and_align_to_aliases(self):
        # A shorthand map lookup and a HogQL transform, appended after the fixed columns.
        # Exact expected values fail if the positional result mapping (result[_FIXED_COLUMN_COUNT:])
        # drifts off the fixed column count, or if either resolution tier breaks.
        shorthand = "resource_attributes.k8s.container.name"
        expression = "upper(service_name)"
        response = self._run([shorthand, expression])

        self.assertEqual(response.columns, [canonical_key(shorthand), canonical_key(expression)])
        self.assertEqual(len(response.results), 1)
        row = response.results[0]
        self.assertEqual(row[canonical_key(shorthand)], "argo-rollouts-dashboard")
        self.assertEqual(row[canonical_key(expression)], "ARGO-ROLLOUTS")

    def test_no_custom_columns_leaves_columns_null(self):
        # The frontend keys off a null `columns` to decide there are no custom columns to render.
        response = self._run([])
        self.assertIsNone(response.columns)
        self.assertEqual(len(response.results), 1)

    def test_too_many_custom_columns_rejected_by_runner(self):
        # The cap is enforced in the runner so every LogsQuery entry point is bounded — including
        # the CSV export worker, which copies query_data straight into a LogsQuery without the
        # interactive endpoint's 400 check. Exceeding the cap must fail before the query runs.
        with self.assertRaises(QueryError):
            self._run(["service_name"] * (MAX_CUSTOM_COLUMNS + 1))
