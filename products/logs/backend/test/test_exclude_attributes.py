import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, LogsQuery

from posthog.clickhouse.client import sync_execute

from products.logs.backend.logs_query_runner import LogsQueryRunner

# The shipped fixture log is timestamped 2025-12-16 and carries both attributes and
# resource_attributes, so it exercises the exclusion of both maps.
DATE_FROM = "2025-12-16T00:00:00Z"
DATE_TO = "2025-12-17T00:00:00Z"


class TestLogsExcludeAttributes(ClickhouseTestMixin, APIBaseTest):
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

    def _run(self, *, exclude: bool, custom_columns: list[str] | None = None) -> list[dict]:
        query = LogsQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            serviceNames=["argo-rollouts"],
            severityLevels=[],
            filterGroup={"type": "AND", "values": []},
            excludeAttributes=exclude,
            customColumns=custom_columns or [],
        )
        return LogsQueryRunner(query, self.team).run().results

    @parameterized.expand(
        [
            ("included_by_default", False),
            ("omitted_when_excluded", True),
        ]
    )
    def test_attributes(self, _name, exclude):
        results = self._run(exclude=exclude)
        self.assertEqual(len(results), 1)
        if exclude:
            # Keys stay present (positional result mapping is stable) but the maps are empty.
            self.assertEqual(results[0]["attributes"], {})
            self.assertEqual(results[0]["resource_attributes"], {})
        else:
            self.assertTrue(results[0]["attributes"])
            self.assertEqual(results[0]["resource_attributes"]["service.name"], "argo-rollouts")

    def test_custom_column_indexing_attribute_key_with_exclusion(self):
        # A custom column that indexes into an attribute map is lowered to arrayElement(map, 'key').
        # When attributes are excluded the map is replaced by a placeholder; that placeholder must
        # carry a real key type or ClickHouse rejects arrayElement with "Illegal types of arguments:
        # Map(Nothing, Nothing), String" and the whole query hard-fails. Assert the query runs.
        results = self._run(exclude=True, custom_columns=["resource_attributes.k8s.container.name"])
        self.assertEqual(len(results), 1)
