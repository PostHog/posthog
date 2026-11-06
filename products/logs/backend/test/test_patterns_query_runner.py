import os
import re
import json
import datetime as dt

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.patterns_query_runner import PatternsQueryRunner, _sample_divisor, _time_slices

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

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_mines_stored_patterns_and_retains_body_examples(self) -> None:
        self._insert(
            [
                {**self._log("Archive job run_A7c queued"), "pattern": "Archive job <ID> queued", "pattern_version": 5},
                {**self._log("Archive job run_B8d queued"), "pattern": "Archive job <ID> queued", "pattern_version": 5},
                {
                    **self._log("Processed 12 records " + "🦔" * 4100),
                    "pattern": "Processed <N> records",
                    "pattern_version": 5,
                },
            ]
        )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            results = self._run()
        patterns = {pattern["pattern"]: pattern for pattern in results["patterns"]}

        assert results["total_count"] == results["scanned_count"] == 3
        assert patterns["Archive job <ID> queued"]["count"] == 2
        assert {example["body"] for example in patterns["Archive job <ID> queued"]["examples"]} == {
            "Archive job run_A7c queued",
            "Archive job run_B8d queued",
        }
        assert patterns["Processed <N> records"]["count"] == 1
        assert len(patterns["Processed <N> records"]["examples"][0]["body"]) == 4096
        assert patterns["Processed <N> records"]["examples"][0]["body"].endswith("🦔")
        assert results["source"] == "stored_patterns"
        assert results["pattern_version"] == 5
        assert results["fallback_reason"] is None
        assert results["represented_count"] == 3
        assert results["remainder_count"] == 0
        assert results["sampled"] is False
        assert patterns["Archive job <ID> queued"]["match_patterns"] == ["Archive job <ID> queued"]
        assert patterns["Archive job <ID> queued"]["pattern_version"] == 5

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_stored_examples_do_not_repeat_a_body(self) -> None:
        self._insert(
            [
                {**self._log("Retry 7 timed out"), "pattern": "Retry <N> timed out", "pattern_version": 5}
                for _ in range(12)
            ]
            + [
                {**self._log("Retry 8 timed out", minute=1), "pattern": "Retry <N> timed out", "pattern_version": 5},
                {**self._log("Retry 9 timed out", minute=2), "pattern": "Retry <N> timed out", "pattern_version": 5},
            ]
        )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            results = self._run()

        pattern = results["patterns"][0]
        bodies = [example["body"] for example in pattern["examples"]]
        assert pattern["count"] == 14
        assert len(bodies) == len(set(bodies))
        assert set(bodies) == {"Retry 7 timed out", "Retry 8 timed out", "Retry 9 timed out"}

    @parameterized.expand([(False, 100, "flag_disabled"), (True, 98, "insufficient_version_coverage")])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_body_fallback_does_not_mix_stored_versions(self, enabled: bool, coverage: int, reason: str) -> None:
        self._insert(
            [
                {**self._log(f"Processed {index} records"), "pattern": "unrelated stored shape", "pattern_version": 3}
                for index in range(coverage)
            ]
            + [self._log("Processed 123 records") for _ in range(100 - coverage)]
        )
        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            results = self._run()
        assert results["source"] == "body_mining"
        assert results["pattern_version"] is None
        assert results["fallback_reason"] == reason
        assert results["remainder_count"] is None
        assert results["patterns"][0]["pattern"] == "Processed <num> records"
        assert results["patterns"][0]["count"] == 100
        assert results["patterns"][0]["match_patterns"] == []

    @parameterized.expand([(0, "", False), (5, "Processed <N> records", False), (0, "", True)])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_dominant_version_aggregates_exact_counts_and_discloses_remainder(
        self, minority_version: int, minority_pattern: str, byte_limited: bool
    ) -> None:
        self._insert(
            [
                {
                    **self._log("Processed 123 records", severity="ERROR", minute=1),
                    "pattern": "Processed <N> records",
                    "pattern_version": 3,
                }
                for _ in range(60)
            ]
            + [
                {**self._log("Archived 456 files", minute=2), "pattern": "Archived <N> files", "pattern_version": 3}
                for _ in range(39)
            ]
            + [{**self._log("Processed 789 records"), "pattern": minority_pattern, "pattern_version": minority_version}]
        )
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch.dict(os.environ, {"LOGS_PATTERNS_HEAD_LIMIT": "10000" if byte_limited else "1"}),
            patch(
                "products.logs.backend.patterns_query_runner.STORED_PATTERN_HEAD_MAX_BYTES",
                42 if byte_limited else 65536,
            ),
        ):
            results = self._run()
        assert results["source"] == "stored_patterns"
        assert results["pattern_version"] == 3
        assert results["pattern_coverage_pct"] == 99
        assert results["total_count"] == 100
        assert results["represented_count"] == 60
        assert results["remainder_count"] == 40
        pattern = results["patterns"][0]
        assert pattern["count"] == pattern["estimated_count"] == 60
        assert pattern["error_count"] == pattern["estimated_error_count"] == 60
        assert pattern["severity_counts"] == {"error": 60}
        assert sum(pattern["sparkline"]) == 60
        assert pattern["volume_share_pct"] == 60
        pivot = self._run(
            filterGroup={
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "pattern", "value": pattern["match_patterns"], "operator": "exact", "type": "log"},
                            {
                                "key": "pattern_version",
                                "value": pattern["pattern_version"],
                                "operator": "exact",
                                "type": "log",
                            },
                        ],
                    }
                ],
            }
        )
        assert pivot["total_count"] == 60

    @parameterized.expand([(True, 5, [60, 50, 40, 30]), (True, 0, [60, 50]), (False, 5, [60, 60])])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_query_budget_covers_stored_queries_and_fallback(
        self, enabled: bool, version: int, expected_budgets: list[int]
    ) -> None:
        self._insert(
            [{**self._log("Processed 7 records"), "pattern": "Processed <N> records", "pattern_version": version}]
        )
        budgets = []
        with (
            patch("posthoganalytics.feature_enabled", return_value=enabled),
            patch("products.logs.backend.patterns_query_runner.monotonic", return_value=100.0) as clock,
        ):

            def execute_with_elapsed_time(*args, **kwargs):
                budgets.append(kwargs["settings"].max_execution_time)
                result = execute_hogql_query(*args, **kwargs)
                clock.return_value += 10
                return result

            with patch(
                "products.logs.backend.patterns_query_runner.execute_hogql_query", side_effect=execute_with_elapsed_time
            ):
                results = self._run()

        assert results["total_count"] == 1
        assert budgets == expected_budgets

    @parameterized.expand([30, 60])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_exhausted_query_budget_raises_instead_of_returning_partial_counts(self, elapsed: int) -> None:
        self._insert([{**self._log("Processed 7 records"), "pattern": "Processed <N> records", "pattern_version": 5}])
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch("products.logs.backend.patterns_query_runner.monotonic", return_value=100.0) as clock,
        ):

            def execute_with_elapsed_time(*args, **kwargs):
                result = execute_hogql_query(*args, **kwargs)
                clock.return_value += elapsed
                return result

            with (
                patch(
                    "products.logs.backend.patterns_query_runner.execute_hogql_query",
                    side_effect=execute_with_elapsed_time,
                ) as execute,
                self.assertRaises(ClickHouseQueryTimeOut),
            ):
                self._run()
            assert execute.call_count == 60 // elapsed

    @time_machine.travel(_FROZEN_NOW, tick=False)
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
        assert results["sample_coverage_pct"] == 100.0
        by_template = {p["pattern"]: p for p in patterns}
        assert "User <*> not found" in by_template
        assert by_template["User <*> not found"]["count"] == 3
        # Unsampled window: estimates equal exact counts.
        assert by_template["User <*> not found"]["estimated_count"] == 3
        assert by_template["User <*> not found"]["error_count"] == 3
        assert by_template["User <*> not found"]["estimated_error_count"] == 3
        assert by_template["User <*> not found"]["severity_counts"] == {"error": 3}
        assert by_template["User <*> not found"]["services"] == ["auth"]
        # Examples are structured sampled rows, not bare bodies.
        example = by_template["User <*> not found"]["examples"][0]
        assert example["body"] == "User alice not found"
        assert example["severity_text"] == "error"
        assert example["service_name"] == "auth"
        assert example["timestamp"].startswith("2026-06-23T12:00:00")
        # The pivot predicate ships validated: it must match the pattern's own examples.
        assert re.search(by_template["User <*> not found"]["match_regex"], example["body"])
        assert by_template["User <*> not found"]["match_literal"] == "not found"
        # Unsliced windows bucket uniformly; every sampled occurrence lands in some bucket.
        assert len(results["sparkline_buckets"]) == 24
        assert sum(by_template["User <*> not found"]["sparkline"]) == 3

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_sets_sampled_and_caps_scanned_count_above_the_limit(self) -> None:
        self._insert([self._log(f"request {i} handled") for i in range(20)])

        with patch.dict(os.environ, {"LOGS_PATTERNS_SAMPLE_LIMIT": "5"}):
            results = self._run()

        assert results["sampled"] is True
        assert results["scanned_count"] <= 5
        # total_count reports the full window size even though the sample is capped.
        assert results["total_count"] == 20

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_sampled_runs_are_deterministic(self) -> None:
        # The sample hashes each row's immutable uuid rather than using rand(), so the same
        # window + filters must mine identical patterns on every run. Guards against
        # reintroducing per-query randomness, which made sampled results unreproducible.
        self._insert([self._log(f"job {chr(97 + i)} finished with status ok") for i in range(40)])

        with patch.dict(os.environ, {"LOGS_PATTERNS_SAMPLE_LIMIT": "20"}):
            first = self._run()
            second = self._run()

        assert first["sampled"] is True
        assert first["patterns"] == second["patterns"]
        assert first["scanned_count"] == second["scanned_count"]

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_scan_budget_bounds_eligible_rows_via_time_slices(self) -> None:
        # 60 rows, one per minute across a 1h window; a budget of 30 with 6 slices makes only
        # half the window eligible. No hash sampling kicks in (pool < sample limit), so the
        # run is fully deterministic: every eligible row is scanned, and estimates scale the
        # sample back up to the window total. The counts are still extrapolated (30 scanned of
        # 60), so `sampled` must stay True even though hash-mod sampling never activated —
        # otherwise the UI renders the estimates as exact.
        self._insert([self._log("tick", minute=m) for m in range(60)])
        window = DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z")

        with patch.dict(os.environ, {"LOGS_PATTERNS_MAX_SCAN_ROWS": "30", "LOGS_PATTERNS_SLICE_COUNT": "6"}):
            results = self._run(dateRange=window)

        assert results["total_count"] == 60
        assert results["scanned_count"] == 30
        assert results["sample_coverage_pct"] == 50.0
        assert results["sampled"] is True
        (pattern,) = results["patterns"]
        assert pattern["count"] == 30
        assert pattern["estimated_count"] == 60
        # Sliced scans use the slices as sparkline buckets: 6 slices x 5 eligible rows each,
        # extrapolated by the same x2 factor as estimated_count.
        assert len(results["sparkline_buckets"]) == 6
        assert pattern["sparkline"] == [10] * 6

    @parameterized.expand(
        [
            ("under_budget", 100, 200, None),
            ("at_budget", 100, 100, None),
        ]
    )
    def test_time_slices_skipped_when_window_fits_budget(self, _name, total, budget, expected) -> None:
        assert (
            _time_slices(
                dt.datetime(2026, 6, 23, 0, 0),
                dt.datetime(2026, 6, 23, 1, 0),
                total=total,
                scan_budget=budget,
                slice_count=4,
            )
            is expected
        )

    def test_time_slices_cover_budget_fraction_and_align_to_window_end(self) -> None:
        date_from = dt.datetime(2026, 6, 23, 0, 0)
        date_to = dt.datetime(2026, 6, 23, 1, 0)

        slices = _time_slices(date_from, date_to, total=200, scan_budget=100, slice_count=4)

        assert slices is not None
        assert len(slices) == 4
        # Coverage 0.5 over 60min in 4 slices -> each slice is 7.5min wide.
        assert all(end - start == dt.timedelta(minutes=7.5) for start, end in slices)
        # Last slice ends at the window end so the freshest logs stay eligible.
        assert slices[-1][1] == date_to
        # Slices stay within the window and don't overlap.
        assert slices[0][0] >= date_from
        assert all(slices[i][1] <= slices[i + 1][0] for i in range(len(slices) - 1))

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

    @parameterized.expand([(False,), (True,)])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_respects_service_filter(self, stored_patterns: bool) -> None:
        self._insert(
            [
                {**self._log("auth check passed", service="api"), "pattern": "auth check passed", "pattern_version": 3}
                for _ in range(3)
            ]
            + [self._log("query took too long", service="db") for _ in range(2)]
        )

        with patch("posthoganalytics.feature_enabled", return_value=stored_patterns):
            results = self._run(serviceNames=["api"])

        assert results["scanned_count"] == 3
        assert results["sampled"] is False
        services_seen = {svc for p in results["patterns"] for svc in p["services"]}
        assert services_seen == {"api"}
        assert results["source"] == ("stored_patterns" if stored_patterns else "body_mining")

    @parameterized.expand([(False,), (True,)])
    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_empty_window_returns_no_patterns(self, enabled: bool) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            results = self._run()

        assert results["patterns"] == []
        assert results["scanned_count"] == 0
        assert results["total_count"] == 0
        assert results["sampled"] is False
        assert results["source"] == "body_mining"
        assert results["fallback_reason"] == ("empty_window" if enabled else "flag_disabled")

    def test_blocks_generic_query_runner_access(self) -> None:
        from products.access_control.backend.facade.user_access_control import UserAccessControlError

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
