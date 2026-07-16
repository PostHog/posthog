import json
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    LogPropertyFilter,
    LogPropertyFilterType,
    LogsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.logs.log_attributes3 import TABLE_NAME as LOG_ATTRIBUTES3_TABLE_NAME
from posthog.clickhouse.logs.logs34 import TABLE_NAME as LOGS_TABLE_NAME

from products.logs.backend.group_by_query_runner import LogsGroupByQueryRunner

_FROZEN_NOW = "2026-06-23T13:00:00Z"
_WINDOW = DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z")


def _filter_group(*filters: LogPropertyFilter) -> PropertyGroupFilter:
    return PropertyGroupFilter(
        type=FilterLogicalOperator.AND_,
        values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=list(filters))],
    )


def _log_property_filter(key: str, filter_type: LogPropertyFilterType, value: str) -> LogPropertyFilter:
    return LogPropertyFilter(key=key, operator=PropertyOperator.EXACT, type=filter_type, value=[value])


class TestGroupByQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Kept ClickHouse databases outlive the Postgres test database, whose team-id
        # sequence restarts every run — so a previous run's rows can share this run's team
        # ids. conftest's reset_clickhouse_tables clears these at session teardown; this
        # covers what it misses (interrupted runs, SKIP_CLICKHOUSE_RESET).
        sync_execute(f"TRUNCATE TABLE IF EXISTS {LOGS_TABLE_NAME}")
        sync_execute(f"TRUNCATE TABLE IF EXISTS {LOG_ATTRIBUTES3_TABLE_NAME}")

    def _insert(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs_distributed FORMAT JSONEachRow\n{sql}")

    def _log(
        self,
        severity: str = "info",
        service: str = "api",
        hour: int = 12,
        minute: int = 0,
        attributes: dict | None = None,
        resource_attributes: dict | None = None,
    ) -> dict:
        row: dict = {
            "timestamp": f"2026-06-23 {hour:02d}:{minute:02d}:00.000000",
            "body": "log line",
            "severity_text": severity,
            "service_name": service,
        }
        if attributes:
            # `attributes` on the real table is an ALIAS over the type-suffixed physical map;
            # inserts must target `attributes_map_str` like ingestion does.
            row["attributes_map_str"] = {f"{k}__str": v for k, v in attributes.items()}
        if resource_attributes:
            row["resource_attributes"] = resource_attributes
        return row

    def _runner(
        self,
        group_by: str,
        group_by_source: str = "log",
        order_groups_by: str = "log_count",
        group_limit: int = 100,
        service_names: list[str] | None = None,
        severity_levels: list[str] | None = None,
        search_term: str | None = None,
        filter_group: PropertyGroupFilter | None = None,
    ) -> LogsGroupByQueryRunner:
        query = LogsQuery(
            dateRange=_WINDOW,
            filterGroup=filter_group or PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=severity_levels or [],
            serviceNames=service_names or [],
            searchTerm=search_term,
        )
        return LogsGroupByQueryRunner(
            team=self.team,
            query=query,
            group_by=group_by,
            group_by_source=group_by_source,
            order_groups_by=order_groups_by,
            group_limit=group_limit,
        )

    def _run(self, group_by: str, **kwargs: Any) -> dict[str, Any]:
        results = self._runner(group_by, **kwargs).calculate().results
        assert isinstance(results, dict)
        return results

    @freeze_time(_FROZEN_NOW)
    def test_groups_by_log_attribute_with_counts_and_last_seen(self) -> None:
        self._insert(
            [
                self._log(attributes={"session_id": "s1"}, severity="info", minute=0),
                self._log(attributes={"session_id": "s1"}, severity="error", minute=1),
                self._log(attributes={"session_id": "s1"}, severity="fatal", minute=2),
                self._log(attributes={"session_id": "s2"}, severity="info", minute=15),
                self._log(attributes={"session_id": "s2"}, severity="info", minute=16),
                # No session_id: must not surface as an empty-valued group.
                self._log(severity="error", minute=7),
            ]
        )

        results = self._run("session_id")

        assert results["total_groups"] == 2
        assert results["total_logs"] == 5
        assert results["truncated"] is False
        s1, s2 = results["groups"]
        # last_seen comes from the rollup path here, so it has 10-minute bucket precision.
        assert s1 == {"value": "s1", "log_count": 3, "error_count": 2, "last_seen": "2026-06-23T12:00:00+00:00"}
        assert s2 == {"value": "s2", "log_count": 2, "error_count": 0, "last_seen": "2026-06-23T12:10:00+00:00"}

    @parameterized.expand(
        [
            ("resource_attribute", "env", "resource", ["prod", "dev"]),
            ("top_level_column", "severity_level", "column", ["error", "info"]),
        ]
    )
    @freeze_time(_FROZEN_NOW)
    def test_groups_by_source(self, _name: str, group_by: str, source: str, expected_values: list[str]) -> None:
        self._insert(
            [
                self._log(resource_attributes={"env": "prod"}, severity="error", minute=0),
                self._log(resource_attributes={"env": "prod"}, severity="error", minute=1),
                self._log(resource_attributes={"env": "dev"}, severity="info", minute=2),
            ]
        )

        results = self._run(group_by, group_by_source=source)

        assert [g["value"] for g in results["groups"]] == expected_values
        assert [g["log_count"] for g in results["groups"]] == [2, 1]

    @freeze_time(_FROZEN_NOW)
    def test_limit_truncates_but_reports_full_totals(self) -> None:
        self._insert(
            [self._log(attributes={"session_id": f"s{i}"}, minute=i) for i in range(3)]
            + [self._log(attributes={"session_id": "s0"}, minute=10)]
        )

        results = self._run("session_id", group_limit=2)

        assert len(results["groups"]) == 2
        assert results["groups"][0]["value"] == "s0"
        assert results["total_groups"] == 3
        assert results["total_logs"] == 4
        assert results["truncated"] is True

    @freeze_time(_FROZEN_NOW)
    def test_order_groups_by_error_count_reranks(self) -> None:
        self._insert(
            [self._log(attributes={"session_id": "noisy"}, severity="info", minute=m) for m in range(3)]
            + [self._log(attributes={"session_id": "failing"}, severity="error", minute=m) for m in range(2)]
        )

        by_count = self._run("session_id")
        by_errors = self._run("session_id", order_groups_by="error_count")

        assert [g["value"] for g in by_count["groups"]] == ["noisy", "failing"]
        assert [g["value"] for g in by_errors["groups"]] == ["failing", "noisy"]

    @parameterized.expand(
        [
            # Rollup path: bounds must land on the right 10-minute buckets.
            ("rollup", None),
            # Logs-scan path: the shared filter builder bounds only time_bucket (day precision);
            # the runner must add per-row timestamp bounds or same-day rows outside the window
            # leak into counts.
            ("logs_scan", "log line"),
        ]
    )
    @freeze_time(_FROZEN_NOW)
    def test_window_bounds_exclude_same_day_rows_outside_window(self, _name: str, search_term: str | None) -> None:
        self._insert(
            [
                self._log(attributes={"session_id": "s1"}, hour=11, minute=30),
                self._log(attributes={"session_id": "s1"}, hour=12, minute=30),
            ]
        )

        results = self._run("session_id", search_term=search_term)

        assert results["total_logs"] == 1
        assert results["groups"][0]["log_count"] == 1

    @freeze_time(_FROZEN_NOW)
    def test_respects_service_filter(self) -> None:
        self._insert(
            [
                self._log(attributes={"session_id": "s1"}, service="api"),
                self._log(attributes={"session_id": "s2"}, service="db", minute=1),
            ]
        )

        results = self._run("session_id", service_names=["api"])

        assert [g["value"] for g in results["groups"]] == ["s1"]

    @parameterized.expand(
        [
            ("no_filters", {}, "log_attributes"),
            ("resource_source", {"group_by_source": "resource"}, "log_attributes"),
            ("severity_levels", {"severity_levels": ["error"]}, "log_attributes"),
            (
                "severity_level_log_filter",
                {
                    "filter_group": _filter_group(
                        _log_property_filter("severity_level", LogPropertyFilterType.LOG, "error")
                    )
                },
                "log_attributes",
            ),
            (
                "resource_attribute_filter",
                {
                    "filter_group": _filter_group(
                        _log_property_filter("env", LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE, "prod")
                    )
                },
                "log_attributes",
            ),
            ("column_source", {"group_by": "severity_level", "group_by_source": "column"}, "logs"),
            ("search_term", {"search_term": "boom"}, "logs"),
            (
                "log_attribute_filter",
                {
                    "filter_group": _filter_group(
                        _log_property_filter("session_id", LogPropertyFilterType.LOG_ATTRIBUTE, "s1")
                    )
                },
                "logs",
            ),
            (
                "non_severity_log_filter",
                {"filter_group": _filter_group(_log_property_filter("trace_id", LogPropertyFilterType.LOG, "abc"))},
                "logs",
            ),
        ]
    )
    @freeze_time(_FROZEN_NOW)
    def test_routes_to_rollup_only_when_filters_are_expressible(
        self, _name: str, kwargs: dict[str, Any], expected_table: str
    ) -> None:
        # Routing to the wrong table means silently wrong counts (rollup can't express the
        # filter) or read-cap failures at scale (logs scan where the rollup would do).
        runner = self._runner(kwargs.pop("group_by", "session_id"), **kwargs)

        outer = runner.to_query()
        assert outer.select_from is not None
        inner = outer.select_from.table
        assert isinstance(inner, ast.SelectQuery)
        assert inner.select_from is not None
        table = inner.select_from.table
        assert isinstance(table, ast.Field)
        assert table.chain == [expected_table]

    @freeze_time(_FROZEN_NOW)
    def test_severity_filter_scopes_rollup_counts(self) -> None:
        # The rollup path must apply severity predicates via its severity_text dimension;
        # dropping them would count logs of every severity.
        self._insert(
            [
                self._log(attributes={"session_id": "s1"}, severity="error", minute=0),
                self._log(attributes={"session_id": "s1"}, severity="info", minute=1),
                self._log(attributes={"session_id": "s2"}, severity="info", minute=2),
            ]
        )

        results = self._run("session_id", severity_levels=["error"])

        assert results["total_logs"] == 1
        assert results["groups"] == [
            {"value": "s1", "log_count": 1, "error_count": 1, "last_seen": "2026-06-23T12:00:00+00:00"}
        ]

    @freeze_time(_FROZEN_NOW)
    def test_resource_attribute_filter_scopes_rollup_counts(self) -> None:
        # Resource-attribute filters stay on the rollup path (fingerprint subquery); losing
        # that wiring would silently ignore the filter and overcount.
        self._insert(
            [
                self._log(attributes={"session_id": "s1"}, resource_attributes={"env": "prod"}),
                self._log(attributes={"session_id": "s2"}, resource_attributes={"env": "dev"}, minute=1),
            ]
        )

        results = self._run(
            "session_id",
            filter_group=_filter_group(
                _log_property_filter("env", LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE, "prod")
            ),
        )

        assert [g["value"] for g in results["groups"]] == ["s1"]
        assert results["total_logs"] == 1

    @parameterized.expand(
        [
            ("missing_group_by", "", "log", "log_count"),
            ("unknown_source", "session_id", "nope", "log_count"),
            # The column path parses a fixed expression allowlist; arbitrary keys must never
            # reach parse_expr, where they would execute as HogQL.
            ("column_not_in_allowlist", "attributes['x'] OR 1=1", "column", "log_count"),
            ("unknown_order_field", "session_id", "log", "value"),
        ]
    )
    def test_invalid_args_raise(self, _name: str, group_by: str, source: str, order: str) -> None:
        query = LogsQuery(
            dateRange=_WINDOW,
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[],
            searchTerm=None,
        )
        with self.assertRaises(ValueError):
            LogsGroupByQueryRunner(
                team=self.team,
                query=query,
                group_by=group_by,
                group_by_source=source,
                order_groups_by=order,
            )


class TestGroupByAPI(ClickhouseTestMixin, APIBaseTest):
    @freeze_time(_FROZEN_NOW)
    def test_endpoint_returns_grouped_results(self) -> None:
        sync_execute(
            "INSERT INTO logs_distributed FORMAT JSONEachRow\n"
            + json.dumps(
                {
                    "team_id": self.team.id,
                    "timestamp": "2026-06-23 12:00:00.000000",
                    "body": "log line",
                    "severity_text": "error",
                    "service_name": "api",
                    "attributes_map_str": {"session_id__str": "s1"},
                }
            )
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/group-by",
            data={
                "query": {
                    "dateRange": {"date_from": "2026-06-23T12:00:00Z", "date_to": "2026-06-23T13:00:00Z"},
                    "groupBy": "session_id",
                }
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_groups"] == 1
        assert data["groups"] == [
            {"value": "s1", "log_count": 1, "error_count": 1, "last_seen": "2026-06-23T12:00:00+00:00"}
        ]

    def test_endpoint_rejects_missing_group_by(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/group-by",
            data={"query": {"dateRange": {"date_from": "-1h"}}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
