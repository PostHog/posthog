import os
import json

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes

_FIXTURE_WINDOW = {"date_from": "2025-12-14T00:00:00Z", "date_to": "2025-12-19T00:00:00Z"}
# A tightly bounded window of the kind an agent uses to measure one service.
_NINETY_MINUTES = {"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T10:30:00Z"}


class TestCountApi(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def _count(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/count", data={"query": query_params})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @parameterized.expand(
        [
            ("full_window", _FIXTURE_WINDOW, 1011),
            ("empty_window", {"date_from": "2000-01-01T00:00:00Z", "date_to": "2000-01-02T00:00:00Z"}, 0),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_date_range(self, _name, date_range, expected):
        response = self._count({"dateRange": date_range})
        self.assertEqual(response["count"], expected)

    @parameterized.expand(
        [
            (["info"], 848),
            (["debug"], 66),
            (["error"], 97),
            (["info", "error"], 945),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_severity_filter(self, severities, expected):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "severityLevels": severities})
        self.assertEqual(response["count"], expected)

    @parameterized.expand(
        [
            (["argo-rollouts"], 100),
            (["contour"], 100),
            (["argo-rollouts", "contour"], 200),
            (["nonexistent-service-xyz"], 0),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_service_filter(self, services, expected):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "serviceNames": services})
        self.assertEqual(response["count"], expected)

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_single_service_over_ninety_minutes_matches_query_logs(self):
        params = {"dateRange": _NINETY_MINUTES, "serviceNames": ["argo-rollouts"]}
        count = self._count(params)["count"]

        logs_response = self.client.post(
            f"/api/projects/{self.team.id}/logs/query",
            data={"query": {**params, "limit": 1000}},
        )
        self.assertEqual(logs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(count, len(logs_response.json()["results"]))

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_read_cap_breach_returns_the_cause(self):
        # The count runs under a ClickHouse read cap. Breaching it used to escape the action as a
        # bare 500, so the caller could not tell a capped scan from a broken endpoint.
        with patch(
            "products.logs.backend.presentation.views.api.CountQueryRunner.run",
            side_effect=CHQueryErrorTooManyBytes("DB::Exception: Limit for bytes to read exceeded"),
        ):
            response = self._count({"dateRange": _FIXTURE_WINDOW}, expected_status=status.HTTP_400_BAD_REQUEST)
        self.assertIn("bytes to read", response.json()["error"])

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_search_term_matches_body_text(self):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "searchTerm": "connection refused"})
        self.assertEqual(response["count"], 1)

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_defaults_date_range_to_last_hour(self):
        # No dateRange in request; default should be -1h relative to frozen "now".
        # Fixture's latest timestamp is 2025-12-18T02:00Z — outside the last hour.
        response = self._count({})
        self.assertEqual(response["count"], 0)

    def test_count_rejects_non_object_query(self):
        # A non-object `query` (e.g. a bare string) used to crash with an unhandled
        # AttributeError on the first `.get()` call instead of a clean 400.
        response = self.client.post(f"/api/projects/{self.team.id}/logs/count", data={"query": "not-an-object"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            # Multi-day window — exercises full WHERE clause
            ("full_window_no_filters", _FIXTURE_WINDOW, {}),
            ("full_window_severity_info", _FIXTURE_WINDOW, {"severityLevels": ["info"]}),
            ("full_window_service_argo", _FIXTURE_WINDOW, {"serviceNames": ["argo-rollouts"]}),
            # Sub-day window — the case that would fail if count regressed to toStartOfDay precision
            (
                "sub_day_hour",
                {"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T10:00:00Z"},
                {},
            ),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_matches_sparkline_sum(self, _name, date_range, filters):
        # Cross-verify: sum of sparkline bucket counts should equal the scalar count
        # for the same query. Catches drift between the two endpoints' WHERE handling.
        # An explicit empty filterGroup is passed because sparkline currently requires it.
        params = {
            "dateRange": date_range,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            **filters,
        }

        count_result = self._count(params)
        sparkline_response = self.client.post(
            f"/api/projects/{self.team.id}/logs/sparkline",
            data={"query": params},
        )
        self.assertEqual(sparkline_response.status_code, status.HTTP_200_OK)

        sparkline_sum = sum(bucket["count"] for bucket in sparkline_response.json())
        self.assertEqual(count_result["count"], sparkline_sum)
