from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.clickhouse.workload import Workload
from posthog.models.instance_setting import override_instance_config

from products.actions.backend.models.action import Action


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNativeEventsClusterWebQueries(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"))
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]))
        self.enterContext(override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", False))

    @parameterized.expand(
        [
            ("web_overview", {"kind": "WebOverviewQuery", "properties": [], "dateRange": {"date_from": "-7d"}}),
            (
                "web_stats",
                {
                    "kind": "WebStatsTableQuery",
                    "properties": [],
                    "breakdownBy": "Page",
                    "dateRange": {"date_from": "-7d"},
                },
            ),
            ("web_url_search", {"kind": "WebPageURLSearchQuery", "properties": [], "dateRange": {"date_from": "-7d"}}),
            ("web_goals", {"kind": "WebGoalsQuery", "properties": [], "dateRange": {"date_from": "-7d"}}),
        ]
    )
    def test_native_opt_in_reads_only_the_native_cluster(self, _name: str, query: dict[str, Any]) -> None:
        Action.objects.create(team=self.team, name="Viewed a page", steps_json=[{"event": "$pageview"}])
        rows = [[0, 0, "Viewed a page", (0, 0), (0, 0)]] if query["kind"] == "WebGoalsQuery" else []
        with patch("posthog.hogql.query.sync_execute", return_value=(rows, [])) as execute:
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {"query": {**query, "modifiers": {"useNewEventsCluster": True}}, "refresh": "force_blocking"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertTrue(execute.called)
        for call in execute.call_args_list:
            self.assertEqual(call.kwargs["workload"], Workload.NEW_EVENTS_CLUSTER, call.args[0])
            self.assertNotRegex(call.args[0], r"\b(FROM|JOIN)\s+events\b")
