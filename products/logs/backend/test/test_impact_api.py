import json
import uuid

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.logs.backend.models import TeamLogsConfig

_FIXTURE_WINDOW = {"date_from": "2025-12-14T00:00:00Z", "date_to": "2025-12-19T00:00:00Z"}

_ZERO_IMPACT = {"total": 0, "logsWithSessionId": 0, "sessions": 0, "logsWithDistinctId": 0, "users": 0}


def _log_row(
    team_id: int,
    body: str,
    severity_text: str = "info",
    severity_number: int = 9,
    attributes: dict[str, str] | None = None,
    resource_attributes: dict[str, str] | None = None,
) -> dict:
    return {
        "uuid": str(uuid.uuid4()),
        "team_id": team_id,
        "trace_id": "",
        "span_id": "",
        "trace_flags": 0,
        "timestamp": "2025-12-16 09:00:00.000000",
        "observed_timestamp": "2025-12-16 09:00:01.000000",
        "body": body,
        "severity_text": severity_text,
        "severity_number": severity_number,
        "service_name": "checkout",
        "resource_attributes": resource_attributes or {},
        # The ingestion MV writes attributes into the typed map with a `__str` key suffix
        # (posthog/clickhouse/logs/logs34.py); mirror that so the fixture matches production rows.
        "attributes_map_str": {f"{key}__str": value for key, value in (attributes or {}).items()},
        "attributes_map_float3": {},
        "attributes_map_datetime": {},
        "event_name": "",
        "instrumentation_scope": "",
    }


class TestImpactApi(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        rows = [
            _log_row(cls.team.id, "checkout started", attributes={"sessionId": "s1", "posthogDistinctId": "u1"}),
            _log_row(cls.team.id, "cart loaded", attributes={"sessionId": "s1"}),
            _log_row(cls.team.id, "payment authorized", attributes={"session_id": "s2", "distinct_id": "u2"}),
            _log_row(cls.team.id, "receipt rendered", resource_attributes={"sessionId": "s3"}),
            _log_row(cls.team.id, "upstream timed out", severity_text="error", severity_number=17),
            _log_row(cls.team.id, "inventory synced", attributes={"my_session": "s9"}),
        ]
        sql = "\n".join(json.dumps(row) for row in rows)
        sync_execute(f"""
            INSERT INTO logs
            FORMAT JSONEachRow
            {sql}
        """)

    def _impact(self, query_params: dict) -> dict:
        response = self.client.post(f"/api/projects/{self.team.id}/logs/impact", data={"query": query_params})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    @parameterized.expand(
        [
            (
                "full_window",
                _FIXTURE_WINDOW,
                {"total": 6, "logsWithSessionId": 4, "sessions": 3, "logsWithDistinctId": 2, "users": 2},
            ),
            ("empty_window", {"date_from": "2000-01-01T00:00:00Z", "date_to": "2000-01-02T00:00:00Z"}, _ZERO_IMPACT),
        ]
    )
    @freeze_time("2025-12-18T12:00:00Z")
    def test_impact_counts_identity_coverage(self, _name: str, date_range: dict, expected: dict) -> None:
        self.assertEqual(self._impact({"dateRange": date_range}), expected)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_impact_accepts_null_filter_lists(self) -> None:
        response = self._impact({"dateRange": _FIXTURE_WINDOW, "severityLevels": None, "serviceNames": None})
        self.assertEqual(response["total"], 6)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_impact_applies_filters(self) -> None:
        # The only error-severity row carries no identity attributes, so every
        # identity count must drop to zero with it.
        response = self._impact({"dateRange": _FIXTURE_WINDOW, "severityLevels": ["error"]})
        self.assertEqual(response, {**_ZERO_IMPACT, "total": 1})

    @freeze_time("2025-12-18T12:00:00Z")
    def test_impact_counts_team_configured_session_keys(self) -> None:
        TeamLogsConfig.objects.update_or_create(
            team=self.team, defaults={"logs_session_id_attribute_keys": ["my_session"]}
        )
        response = self._impact({"dateRange": _FIXTURE_WINDOW})
        self.assertEqual(response["logsWithSessionId"], 5)
        self.assertEqual(response["sessions"], 4)

    def test_impact_rejects_non_object_query(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/logs/impact", data={"query": "not-an-object"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
