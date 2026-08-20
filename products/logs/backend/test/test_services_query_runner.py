import os
import json
from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.logs.backend import services_query_runner
from products.logs.backend.services_query_runner import rule_could_apply_to_service


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

    def _services(
        self, date_from: str, date_to: str, service_name_search: str | None = None, **query_extra: Any
    ) -> dict:
        query: dict[str, Any] = {
            "dateRange": {"date_from": date_from, "date_to": date_to},
            "severityLevels": [],
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "serviceNames": [],
        }
        if service_name_search is not None:
            query["serviceNameSearch"] = service_name_search
        query.update(query_extra)
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data={"query": query},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    @freeze_time("2025-12-16T10:33:00Z")
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

    @freeze_time("2025-12-16T10:33:00Z")
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

    @freeze_time("2025-12-16T10:33:00Z")
    def test_sparkline_covers_exactly_the_returned_services(self):
        # Exact equality holds because the fixture's 12 services fit within
        # SPARKLINE_SERVICES_LIMIT; past the limit only the top services get a trend.
        result = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")
        service_names = {s["service_name"] for s in result["services"]}
        sparkline_services = {row["service_name"] for row in result["sparkline"]}

        self.assertTrue(service_names)
        self.assertEqual(sparkline_services, service_names)

    # The tests below pass absolute date ranges instead of freezing time: the first
    # request of a test process imports the URLconf, and transitively pydantic.v1,
    # whose date subclasses cannot be built while freezegun has datetime.date patched.
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

    def test_offset_pagination_walks_every_row_once(self):
        full = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")
        self.assertFalse(full["hasMore"])

        pages = []
        offset = 0
        for _ in range(10):
            page = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z", limit=5, offset=offset)
            pages.append(page)
            if not page["hasMore"]:
                break
            offset += len(page["services"])

        self.assertEqual([len(p["services"]) for p in pages], [5, 5, 2])
        self.assertEqual([p["hasMore"] for p in pages], [True, True, False])
        walked = [s["service_name"] for p in pages for s in p["services"]]
        self.assertEqual(walked, [s["service_name"] for s in full["services"]])

    def test_later_pages_share_stays_global_and_skip_sparkline_and_summary(self):
        full = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z")
        share_by_name = {s["service_name"]: s["volume_share_pct"] for s in full["services"]}

        page = self._services("2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z", limit=5, offset=5)

        for s in page["services"]:
            self.assertEqual(s["volume_share_pct"], share_by_name[s["service_name"]])
        self.assertEqual(page["sparkline"], [])
        self.assertNotIn("summary", page)
        self.assertEqual(page["total_services"], 12)

    @parameterized.expand(
        [
            ("service_name_asc", "service_name", "ASC", lambda s: s["service_name"], False),
            ("error_rate_desc", "error_rate", "DESC", lambda s: s["error_rate"], True),
            ("log_count_asc", "log_count", "ASC", lambda s: s["log_count"], False),
        ]
    )
    def test_order_by_applies_server_side(self, _name, order_by, order_direction, sort_key, reverse):
        result = self._services(
            "2025-12-16T00:00:00Z", "2025-12-16T23:59:59Z", orderBy=order_by, orderDirection=order_direction
        )

        keys = [sort_key(s) for s in result["services"]]
        self.assertEqual(len(keys), 12)
        self.assertEqual(keys, sorted(keys, reverse=reverse))

    @parameterized.expand(
        [
            ("limit_zero", {"limit": 0}),
            ("limit_over_max", {"limit": 1001}),
            ("limit_not_an_integer", {"limit": "abc"}),
            ("negative_offset", {"offset": -1}),
            ("unknown_order_by", {"orderBy": "volume"}),
            ("unknown_order_direction", {"orderDirection": "up"}),
        ]
    )
    def test_invalid_pagination_params_are_rejected(self, _name: str, extra: dict):
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/services",
            data={
                "query": {
                    "dateRange": {"date_from": "2025-12-16T00:00:00Z", "date_to": "2025-12-16T23:59:59Z"},
                    "severityLevels": [],
                    "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
                    "serviceNames": [],
                    **extra,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
