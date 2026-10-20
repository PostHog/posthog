import os
import json
import datetime as dt
from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.logs.backend import services_query_runner
from products.logs.backend.services_query_runner import rule_could_apply_to_service
from products.logs.backend.test.volume_rollup_fixtures import insert_logs_and_rollups, log_row


def _wrap(inner: dict) -> dict:
    """Mirror the outer-AND envelope the drop-rules UI emits."""
    return {"type": "AND", "values": [inner]}


def _leaf(key: str, operator: str, value: Any) -> dict:
    return {"key": key, "operator": operator, "value": value, "type": "log_resource_attribute"}


class TestRuleCouldApplyToService:
    """
    Unit tests for the three-valued evaluator that backs the Services tab's
    `active_rules` list. The Node ingestion worker remains the source of truth
    for actual per-record drop decisions; this helper only filters the display
    list so a rule scoped via `filter_group` to one service doesn't appear on
    every service's row.
    """

    def test_empty_or_missing_filter_group_applies_to_every_service(self) -> None:
        assert rule_could_apply_to_service(None, "api") is True
        assert rule_could_apply_to_service({}, "api") is True
        assert rule_could_apply_to_service({"type": "AND", "values": []}, "api") is True

    def test_exact_service_name_match(self) -> None:
        rule = _wrap({"type": "AND", "values": [_leaf("service.name", "exact", "api")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    def test_underscore_key_matches_dotted_key(self) -> None:
        # The Node consumer treats `service_name` and `service.name` as aliases;
        # services-page evaluation should too, so the UI's choice of key doesn't
        # silently change the display semantics.
        rule = _wrap({"type": "AND", "values": [_leaf("service_name", "exact", "api")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    @parameterized.expand(
        [
            ("icontains_match", "icontains", "ap", "api", True),
            ("icontains_no_match", "icontains", "redis", "api", False),
            ("not_icontains_match", "not_icontains", "redis", "api", True),
            ("not_icontains_excludes", "not_icontains", "ap", "api", False),
            ("regex_anchor_match", "regex", "^api$", "api", True),
            ("regex_prefix_match", "regex", "^api", "api-v2", True),
            ("regex_no_match", "regex", "^kafka", "api", False),
            ("not_regex_match", "not_regex", "^kafka", "api", True),
            ("in_list_match", "in", ["api", "kafka"], "api", True),
            ("in_list_no_match", "in", ["redis", "kafka"], "api", False),
            ("not_in_match", "not_in", ["redis", "kafka"], "api", True),
            ("not_in_excludes", "not_in", ["api", "kafka"], "api", False),
            ("is_set_with_value", "is_set", None, "api", True),
            ("is_set_blank", "is_set", None, "", False),
            ("is_not_set_with_value", "is_not_set", None, "api", False),
            ("is_not_set_blank", "is_not_set", None, "", True),
            ("invalid_regex_never_matches", "regex", "[unclosed", "api", False),
            ("invalid_not_regex_is_indeterminate", "not_regex", "[unclosed", "api", True),
        ]
    )
    def test_service_leaf_operators(
        self, _label: str, operator: str, value: Any, service_name: str, expected: bool
    ) -> None:
        rule = _wrap({"type": "AND", "values": [_leaf("service.name", operator, value)]})
        assert rule_could_apply_to_service(rule, service_name) is expected

    def test_non_service_leaf_is_indeterminate(self) -> None:
        # A rule scoped only by attributes can match some logs on any service —
        # we can't know without seeing the row. Keep the rule visible.
        rule = _wrap({"type": "AND", "values": [_leaf("severity_text", "exact", "error")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "anything") is True

    def test_and_excludes_when_service_predicate_fails(self) -> None:
        # `service.name = api AND severity = error` → for `other` the service
        # predicate is FALSE, so the AND is FALSE regardless of severity.
        rule = _wrap(
            {
                "type": "AND",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("severity_text", "exact", "error"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True  # might apply (error subset)
        assert rule_could_apply_to_service(rule, "other") is False  # cannot apply

    def test_or_keeps_rule_visible_when_one_branch_indeterminate(self) -> None:
        # `service.name = api OR severity = error` → on `other`, service branch
        # is FALSE but severity branch is INDETERMINATE → INDETERMINATE → keep.
        rule = _wrap(
            {
                "type": "OR",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("severity_text", "exact", "error"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is True  # error logs of `other` would match

    def test_or_all_service_predicates_resolve_negatively(self) -> None:
        # `service.name = api OR service.name = kafka` → on `redis`, both branches
        # FALSE, OR = FALSE, rule excluded.
        rule = _wrap(
            {
                "type": "OR",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("service.name", "exact", "kafka"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "kafka") is True
        assert rule_could_apply_to_service(rule, "redis") is False

    def test_nested_groups(self) -> None:
        # `service.name = api AND (severity = error OR severity = fatal)` —
        # the inner OR is INDETERMINATE (severity unknown), AND with TRUE service
        # match yields INDETERMINATE → keep on `api`. On `other`, the outer AND
        # short-circuits to FALSE.
        rule = _wrap(
            {
                "type": "AND",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    {
                        "type": "OR",
                        "values": [
                            _leaf("severity_text", "exact", "error"),
                            _leaf("severity_text", "exact", "fatal"),
                        ],
                    },
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    def test_malformed_node_falls_back_to_indeterminate(self) -> None:
        # Conservative default: anything we can't parse keeps the rule visible.
        assert rule_could_apply_to_service({"type": "AND", "values": ["oops"]}, "api") is True
        assert rule_could_apply_to_service({"not_a_group": True}, "api") is True


class TestServicesQueryDateRange(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            insert_logs_and_rollups([{**json.loads(line), "team_id": cls.team.id} for line in f])

    def _services(self, date_from: str, date_to: str, service_name_search: str | None = None) -> dict:
        query: dict[str, Any] = {
            "dateRange": {"date_from": date_from, "date_to": date_to},
            "severityLevels": [],
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "serviceNames": [],
        }
        if service_name_search is not None:
            query["serviceNameSearch"] = service_name_search
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data={"query": query},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    @time_machine.travel("2025-12-16T10:33:00Z", tick=False)
    def test_services_honors_sub_day_date_range(self):
        # The fixture has 1003 logs on 2025-12-16 across 12 services, but only the
        # 10:32 batch (100 logs from cdp-legacy-events-consumer) falls in this
        # 9-minute window. The day-level partition filter alone would return the
        # whole day; the precise timestamp bound must narrow it to the window.
        full_day = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")
        windowed = self._services("2025-12-16T10:24:00Z", "2025-12-16T10:33:00Z")

        self.assertEqual(sum(s["log_count"] for s in full_day["services"]), 1003)
        self.assertEqual(len(windowed["services"]), 1)
        self.assertEqual(windowed["services"][0]["service_name"], "cdp-legacy-events-consumer")
        self.assertEqual(windowed["services"][0]["log_count"], 100)

    @time_machine.travel("2025-12-16T10:33:00Z", tick=False)
    def test_services_normalizes_flat_filter_group_from_mcp(self):
        # MCP tools send `filterGroup` as a flat list of property filters (see
        # `_normalize_filter_group`'s docstring), not the nested PropertyGroupFilter shape
        # `_services` above sends. Passing that flat shape straight to `LogsQuery` used to
        # raise an unhandled pydantic ValidationError (500) instead of running the query.
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data={
                "query": {
                    "dateRange": {"date_from": "2025-12-16T00:00:00Z", "date_to": "2025-12-16T23:59:59Z"},
                    "filterGroup": [
                        {
                            "key": "service.name",
                            "type": "log_resource_attribute",
                            "operator": "exact",
                            "value": "cdp-legacy-events-consumer",
                        }
                    ],
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = response.json()["services"]
        self.assertEqual({s["service_name"] for s in services}, {"cdp-legacy-events-consumer"})

    @time_machine.travel("2025-12-16T10:33:00Z", tick=False)
    def test_sparkline_covers_exactly_the_returned_services(self):
        # Exact equality holds because the fixture's 12 services fit within
        # SPARKLINE_SERVICES_LIMIT; past the limit only the top services get a trend.
        result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")
        service_names = {s["service_name"] for s in result["services"]}
        sparkline_services = {row["service_name"] for row in result["sparkline"]}

        self.assertTrue(service_names)
        self.assertEqual(sparkline_services, service_names)

    def test_cap_limits_services_but_not_total_count(self):
        with patch.object(services_query_runner, "SERVICES_LIMIT", 5):
            result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")

        self.assertEqual(len(result["services"]), 5)
        self.assertEqual(result["total_services"], 12)
        # The cap keeps the highest-volume services: every kept fixture service has
        # 97+ rows, so the smallest two (11 and 3 rows) are the ones cut.
        self.assertTrue(all(s["log_count"] >= 97 for s in result["services"]))

    def test_query_count_does_not_grow_with_the_number_of_services(self):
        with patch.object(
            services_query_runner,
            "execute_hogql_query",
            wraps=services_query_runner.execute_hogql_query,
        ) as execute_spy:
            result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")

        # Runs on the shipped cap, so every fixture service comes back untruncated.
        self.assertEqual(len(result["services"]), 12)
        # Counting the services with a second, uncapped scan of the window instead
        # of the aggregates query's window function added 20s on a large project.
        # Fetching rules or sparklines per service would show up here too.
        self.assertEqual(execute_spy.call_count, 2, "expected only the aggregates and sparkline queries")

    def test_sparkline_scoped_to_top_services_when_over_limit(self):
        with patch.object(services_query_runner, "SPARKLINE_SERVICES_LIMIT", 3):
            result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")

        top_names = {s["service_name"] for s in result["services"][:3]}
        sparkline_services = {row["service_name"] for row in result["sparkline"]}
        self.assertEqual(sparkline_services, top_names)

    @parameterized.expand(
        [
            (
                "case_insensitive_substring",
                "CDP",
                {"cdp-legacy-events-consumer", "cdp-api", "cdp-api-webhooks", "cdp-behavioural-events-consumer"},
            ),
            # Unescaped, "%_" matches every service name; no fixture name contains
            # a literal %, _, or backslash.
            ("wildcards_matched_literally", "%_", set()),
            ("backslash_matched_literally", "\\", set()),
        ]
    )
    def test_service_name_search(self, _name: str, search: str, expected_names: set[str]):
        result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z", service_name_search=search)

        self.assertEqual({s["service_name"] for s in result["services"]}, expected_names)
        self.assertEqual(result["total_services"], len(expected_names))


_COMPARE_NOW = "2026-06-23T13:00:00Z"
_CURRENT = {"date_from": "2026-06-23T12:00:00Z", "date_to": "2026-06-23T13:00:00Z"}
_PRODUCTION = {"deployment.environment.name": "production"}
_STAGING = {"deployment.environment": "staging"}
_COMPARE_SERVICES: dict[str, tuple[dict[str, str], tuple[int, int], tuple[int, int]]] = {
    "checkout": (_PRODUCTION, (200, 2), (200, 20)),
    "billing": (_PRODUCTION, (50, 0), (0, 0)),
    "search": (_PRODUCTION, (0, 0), (30, 0)),
    "inventory": ({"env": "production"}, (150, 0), (150, 0)),
    "ledger": (_STAGING, (100, 10), (100, 10)),
    "payments": (_STAGING, (100, 20), (120, 0)),
}


def _hour_rows(team_id: int, service: str, hour: int, info: int, errors: int, resource: dict[str, str]) -> list[dict]:
    total = info + errors
    start = dt.datetime(2026, 6, 23, hour, 0, 30, tzinfo=dt.UTC)
    rows = []
    for i in range(total):
        rows.append(
            log_row(
                team_id,
                start + dt.timedelta(seconds=i * 3540 / total),
                service=service,
                severity="error" if i < errors else "info",
                resource_attributes=resource,
            )
        )
    return rows


class TestServicesCompare(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rows: list[dict] = []
        for service, (resource, (base_info, base_errors), (cur_info, cur_errors)) in _COMPARE_SERVICES.items():
            rows += _hour_rows(cls.team.id, service, 11, base_info, base_errors, resource)
            rows += _hour_rows(cls.team.id, service, 12, cur_info, cur_errors, resource)
        insert_logs_and_rollups(rows)

    def _services(
        self, expected_status: int = status.HTTP_200_OK, baselineDateRange: dict | None = None, **query: Any
    ) -> dict:
        body: dict[str, Any] = {"query": {"dateRange": _CURRENT, **query}}
        if baselineDateRange is not None:
            body["baselineDateRange"] = baselineDateRange
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data=body,
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.content)
        return response.json()

    @staticmethod
    def _by_service(result: dict) -> dict[str, dict]:
        return {row["service_name"]: row for row in result["services"]}

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_previous_period_classifies_each_service(self) -> None:
        result = self._services(compare="previous_period")
        rows = self._by_service(result)

        assert {name: row["status"] for name, row in rows.items()} == {
            "checkout": "regressed",
            "billing": "silent",
            "search": "new",
            "inventory": "ok",
            "ledger": "degraded",
            "payments": "recovered",
        }
        assert rows["checkout"]["reason"] == "error rate 1.0% → 9.1%"
        assert rows["checkout"]["error_rate_pct"] == 9.1
        assert rows["checkout"]["error_rate_delta_pp"] == 8.1
        assert rows["checkout"]["baseline_log_count"] == 202
        assert rows["billing"]["log_count"] == 0
        assert rows["billing"]["baseline_log_count"] == 50
        assert rows["billing"]["last_seen"] == "2026-06-23T11:55:00Z"
        assert result["window"] == {
            "current": {"from": "2026-06-23T12:00:00Z", "to": "2026-06-23T13:00:00Z"},
            "baseline": {"from": "2026-06-23T11:00:00Z", "to": "2026-06-23T12:00:00Z"},
            "timezone": "UTC",
        }
        assert result["summary"]["status_counts"] == {
            "ok": 1,
            "degraded": 1,
            "regressed": 1,
            "improved": 0,
            "recovered": 1,
            "new": 1,
            "silent": 1,
        }
        assert all(len(row["reason"]) <= 80 for row in result["services"])

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_next_suggests_follow_ups_for_problem_services(self) -> None:
        result = self._services(compare="previous_period")

        suggestions = {(step["tool"], tuple(step["query"].get("serviceNames", []))) for step in result["next"]}
        assert ("logs-count-ranges", ("billing",)) in suggestions
        assert ("logs-patterns-diff", ("checkout",)) in suggestions
        assert len(result["next"]) <= 3

    @parameterized.expand(
        [
            ("aligned_window_reads_the_rollup", _CURRENT, "rollup"),
            (
                "unaligned_window_adds_raw_edges",
                {"date_from": "2026-06-23T12:02:10Z", "date_to": "2026-06-23T12:57:50Z"},
                "rollup+raw",
            ),
        ]
    )
    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_rollup_and_raw_paths_give_the_same_counts(self, _name: str, window: dict, expected_source: str) -> None:
        def counts(result: dict) -> dict[str, tuple]:
            return {
                row["service_name"]: (
                    row["log_count"],
                    row["error_count"],
                    row["severity_breakdown"],
                    row["baseline_log_count"],
                    row["status"],
                )
                for row in result["services"]
            }

        fast = self._services(dateRange=window, compare="previous_period")
        with patch.object(services_query_runner.ServicesQueryRunner, "_use_rollup", return_value=False):
            raw = self._services(dateRange=window, compare="previous_period")

        assert fast["source"] == expected_source
        assert raw["source"] == "raw"
        assert counts(fast) == counts(raw)
        assert fast["total_services"] == raw["total_services"]

    @parameterized.expand([("rollup", True), ("raw", False)])
    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_environment_filter_follows_the_fallback_chain(self, _name: str, use_rollup: bool) -> None:
        with patch.object(services_query_runner.ServicesQueryRunner, "_use_rollup", return_value=use_rollup):
            result = self._services(compare="previous_period", environment="production")

        assert set(self._by_service(result)) == {"checkout", "billing", "search", "inventory"}

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_no_compare_keeps_the_single_window_response(self) -> None:
        result = self._services()
        rows = self._by_service(result)

        assert set(rows) == {"checkout", "search", "inventory", "ledger", "payments"}
        assert rows["checkout"]["status"] == "degraded"
        assert rows["inventory"]["status"] == "ok"
        assert rows["inventory"]["baseline_log_count"] is None
        assert "baseline" not in result["window"]
        assert {"sparkline", "total_services", "summary"} <= set(result)

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_explicit_baseline_matches_previous_period(self) -> None:
        explicit = self._services(
            baselineDateRange={"date_from": "2026-06-23T11:00:00Z", "date_to": "2026-06-23T12:00:00Z"}
        )
        previous = self._services(compare="previous_period")

        assert explicit["services"] == previous["services"]

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_previous_day_without_history_marks_every_service_new(self) -> None:
        result = self._services(compare="previous_day")

        assert result["window"]["baseline"] == {"from": "2026-06-22T12:00:00Z", "to": "2026-06-22T13:00:00Z"}
        assert {row["status"] for row in result["services"]} == {"new"}

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_next_keeps_the_original_scope(self) -> None:
        excluded = {
            "key": "k8s.namespace.name",
            "operator": "is_not",
            "value": ["staging"],
            "type": "log_resource_attribute",
        }
        result = self._services(compare="previous_period", searchTerm="log line", filterGroup=[excluded])

        assert result["next"]
        for step in result["next"]:
            assert step["query"]["searchTerm"] == "log line"
            assert step["query"]["filterGroup"] == [excluded]
        diff = next(step for step in result["next"] if step["tool"] == "logs-patterns-diff")
        assert diff["baselineDateRange"] == {"date_from": "2026-06-23T11:00:00Z", "date_to": "2026-06-23T12:00:00Z"}
        assert self._services(compare="previous_period", environment="production")["next"] == []

    def test_next_filters_on_the_stored_service_name(self) -> None:
        window = (dt.datetime(2026, 6, 23, 12, tzinfo=dt.UTC), dt.datetime(2026, 6, 23, 13, tzinfo=dt.UTC))

        steps = services_query_runner._next_steps([("", "degraded")], window, None, {})

        assert {tuple(step["query"]["serviceNames"]) for step in steps} == {("",)}

    @time_machine.travel(_COMPARE_NOW, tick=False)
    def test_a_capped_scan_does_not_invent_silent_or_new_services(self) -> None:
        with patch("products.logs.backend.services_query_runner.SERVICES_LIMIT", 2):
            result = self._services(compare="previous_period")

        assert not {row["status"] for row in result["services"]} & {"silent", "new"}
        assert result["summary"]["truncated"] is True

    def test_environment_must_be_a_string(self) -> None:
        self._services(expected_status=status.HTTP_400_BAD_REQUEST, environment=["production"])

    def test_unknown_compare_mode_is_rejected(self) -> None:
        response = self._services(expected_status=status.HTTP_400_BAD_REQUEST, compare="yesterday")
        assert "compare" in json.dumps(response)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
