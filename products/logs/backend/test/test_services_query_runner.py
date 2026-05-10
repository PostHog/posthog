import json
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestServicesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    """Verifies the per-service aggregation runner used by the Services tab and the
    `logs-services-create` MCP tool. The headline behavior we lock in here is the
    sparkline scope: it must only return rows for the same top-25 services the
    aggregates result returns. Without that filter, the sparkline previously fanned
    out across every service in the window and clipped unpredictably at the LIMIT,
    blowing the response size for any caller that walked it (like an LLM agent)."""

    def setUp(self):
        super().setUp()
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _insert_logs_for_services(self, service_log_counts: dict[str, int], timestamp: str) -> None:
        """Insert N log rows per service at the given timestamp. Counts drive the
        top-25 ordering — services with more rows rank higher in the aggregates."""
        rows = []
        for service_name, count in service_log_counts.items():
            for i in range(count):
                rows.append(
                    {
                        "uuid": f"019d{abs(hash(service_name)) % 10000:04d}-0000-7000-0000-{i:012d}",
                        "team_id": self.team.id,
                        "trace_id": "AAAAAAAAAAAAAAAAAAAAAA==",
                        "span_id": "AAAAAAAAAAA=",
                        "trace_flags": 0,
                        "timestamp": timestamp,
                        "observed_timestamp": timestamp,
                        "body": f"log {i} for {service_name}",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": service_name,
                        "resource_attributes": {},
                        "resource_id": "",
                        "instrumentation_scope": "@",
                        "event_name": "",
                        "attributes_map_str": {},
                        "attributes_map_float3": {},
                        "attributes_map_datetime": {},
                    }
                )
        if not rows:
            return
        sql_payload = "\n".join(json.dumps(r) for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql_payload}")

    def _services_request(self, query_params: dict, expected_status: int = status.HTTP_200_OK) -> Any:
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data={"query": query_params},
            format="json",
        )
        assert response.status_code == expected_status, response.json()
        return response.json() if expected_status == status.HTTP_200_OK else response

    @freeze_time("2026-05-09T12:00:00Z")
    def test_aggregates_returns_top_25_services_by_volume(self):
        # 30 services with strictly decreasing log volumes — top-25 are svc-00..svc-24,
        # tail-5 are svc-25..svc-29.
        self._insert_logs_for_services(
            {f"svc-{i:02d}": 100 - i for i in range(30)},
            timestamp="2026-05-09 11:30:00.000000",
        )

        response = self._services_request(
            {"dateRange": {"date_from": "2026-05-09T11:00:00Z", "date_to": "2026-05-09T12:00:00Z"}}
        )

        services = response["services"]
        assert len(services) == 25
        assert services[0]["service_name"] == "svc-00"
        assert services[0]["log_count"] == 100
        assert services[-1]["service_name"] == "svc-24"
        assert all(s["service_name"].startswith("svc-") for s in services)
        # Tail services excluded from the top-25 must not appear in the aggregates row set.
        returned_names = {s["service_name"] for s in services}
        for tail in (f"svc-{i:02d}" for i in range(25, 30)):
            assert tail not in returned_names

    @freeze_time("2026-05-09T12:00:00Z")
    def test_sparkline_scoped_to_top_services_only(self):
        # Same shape as above — assert that no sparkline row mentions a tail service.
        # This is the regression we are guarding: prior to scoping, the sparkline
        # subquery returned rows for every service in the window, including tail-5.
        self._insert_logs_for_services(
            {f"svc-{i:02d}": 100 - i for i in range(30)},
            timestamp="2026-05-09 11:30:00.000000",
        )

        response = self._services_request(
            {"dateRange": {"date_from": "2026-05-09T11:00:00Z", "date_to": "2026-05-09T12:00:00Z"}}
        )

        sparkline = response["sparkline"]
        assert len(sparkline) > 0
        sparkline_services = {row["service_name"] for row in sparkline}
        aggregates_services = {s["service_name"] for s in response["services"]}

        # Headline assertion — sparkline service-set is a subset of aggregates service-set.
        assert sparkline_services.issubset(aggregates_services), (
            f"sparkline contains services not in top-25 aggregates: {sparkline_services - aggregates_services}"
        )
        # Defensive: explicitly check the tail-5 stay out of the sparkline.
        for tail in (f"svc-{i:02d}" for i in range(25, 30)):
            assert tail not in sparkline_services

    @freeze_time("2026-05-09T12:00:00Z")
    def test_sparkline_omitted_when_no_services_in_window(self):
        # No logs at all → aggregates returns []; sparkline subquery is skipped to
        # avoid an unnecessary round-trip and a degenerate WHERE service_name IN ().
        response = self._services_request(
            {"dateRange": {"date_from": "2026-05-09T11:00:00Z", "date_to": "2026-05-09T12:00:00Z"}}
        )

        assert response["services"] == []
        assert response["sparkline"] == []
