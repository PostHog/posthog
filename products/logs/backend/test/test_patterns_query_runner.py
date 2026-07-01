import os
import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.patterns_query_runner import PatternsQueryRunner, _sample_divisor

_FROZEN_NOW = "2026-06-23T13:00:00Z"
_WINDOW = DateRange(date_from="2026-06-23T00:00:00Z", date_to="2026-06-23T13:00:00Z")


class TestPatternsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _insert(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

    def _log(self, body: str, severity: str = "info", service: str = "api", minute: int = 0) -> dict:
        return {
            "timestamp": f"2026-06-23 12:{minute:02d}:00.000000",
            "body": body,
            "severity_text": severity,
            "service_name": service,
        }

    def _run(self, **overrides) -> dict:
        query = LogsQuery(
            dateRange=overrides.pop("dateRange", _WINDOW),
            filterGroup=overrides.pop("filterGroup", PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[])),
            severityLevels=overrides.pop("severityLevels", []),
            serviceNames=overrides.pop("serviceNames", []),
            searchTerm=overrides.pop("searchTerm", None),
        )
        response = PatternsQueryRunner(team=self.team, query=query).run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return response.results

    @freeze_time(_FROZEN_NOW)
    def test_mines_templates_from_clickhouse(self) -> None:
        self._insert(
            [
                self._log(f"User {name} not found", severity="error", service="auth")
                for name in ("alice", "bob", "carol")
            ]
            + [self._log(f"GET /api/orders/{i} ok", service="api") for i in range(2)]
        )

        results = self._run()
        patterns = results["patterns"]

        assert results["scanned_count"] == 5
        assert results["total_count"] == 5
        assert results["sampled"] is False
        by_template = {p["pattern"]: p for p in patterns}
        assert "User <*> not found" in by_template
        assert by_template["User <*> not found"]["count"] == 3
        assert by_template["User <*> not found"]["error_count"] == 3
        assert by_template["User <*> not found"]["services"] == ["auth"]

    @freeze_time(_FROZEN_NOW)
    def test_sets_sampled_and_caps_scanned_count_above_the_limit(self) -> None:
        self._insert([self._log(f"request {i} handled") for i in range(20)])

        # Only assert invariants that don't depend on the random sample: `sampled` is a
        # deterministic function of total vs. limit, and the LIMIT caps `scanned_count`.
        with patch.dict(os.environ, {"LOGS_PATTERNS_SAMPLE_LIMIT": "5"}):
            results = self._run()

        assert results["sampled"] is True
        assert results["scanned_count"] <= 5
        # total_count reports the full window size even though the sample is capped.
        assert results["total_count"] == 20

    @parameterized.expand(
        [
            (0, 1),
            (5, 1),
            (10, 1),
            (11, 2),
            (15, 2),
            (20, 2),
            (21, 3),
            (100, 10),
        ]
    )
    def test_sample_divisor_rounds_up_to_keep_sample_within_limit(self, total: int, expected: int) -> None:
        assert _sample_divisor(total, sample_limit=10) == expected

    @freeze_time(_FROZEN_NOW)
    def test_respects_service_filter(self) -> None:
        self._insert(
            [self._log("auth check passed", service="api") for _ in range(3)]
            + [self._log("query took too long", service="db") for _ in range(2)]
        )

        results = self._run(serviceNames=["api"])

        assert results["scanned_count"] == 3
        assert results["sampled"] is False
        services_seen = {svc for p in results["patterns"] for svc in p["services"]}
        assert services_seen == {"api"}

    @freeze_time(_FROZEN_NOW)
    def test_empty_window_returns_no_patterns(self) -> None:
        results = self._run()

        assert results["patterns"] == []
        assert results["scanned_count"] == 0
        assert results["total_count"] == 0
        assert results["sampled"] is False

    def test_blocks_generic_query_runner_access(self) -> None:
        from posthog.rbac.user_access_control import UserAccessControlError

        query = LogsQuery(
            dateRange=_WINDOW,
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[],
            searchTerm=None,
        )
        runner = PatternsQueryRunner(team=self.team, query=query)
        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(self.user)
