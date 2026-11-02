import json
import datetime as dt
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    LogPropertyFilter,
    LogsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut

from products.logs.backend.log_patterns import pattern_fingerprint
from products.logs.backend.pattern_diff import (
    _first_seen_ever,
    _raw_lines_call,
    diff_patterns,
    run_patterns_diff,
    stored_pattern_keys,
)
from products.logs.backend.patterns_query_runner import PatternsQueryRunner

_HOUR = (dt.datetime(2026, 6, 23, 12, 0), dt.datetime(2026, 6, 23, 13, 0))
_BASELINE_HOUR = (dt.datetime(2026, 6, 16, 12, 0), dt.datetime(2026, 6, 16, 13, 0))
_BASELINE_TWO_HOURS = (dt.datetime(2026, 6, 16, 11, 0), dt.datetime(2026, 6, 16, 13, 0))


def _pattern(template: str, *, count: int = 50, share: float = 10.0, severities: dict | None = None) -> dict:
    # Only the fields the diff reads; the runner's serializer owns the full shape.
    return {
        "pattern": template,
        "count": count,
        "estimated_count": count,
        "volume_share_pct": share,
        "severity_counts": severities if severities is not None else {"info": count},
    }


class TestPatternFingerprint(TestCase):
    @parameterized.expand(
        [
            ("placeholder_kind_wobble", "User <*> not found", "User <num> not found", True),
            ("placeholder_widening_preserved_literals", "job <*> done in <num>ms", "job <hex> done in <*>ms", True),
            ("different_literals", "User <*> not found", "User <*> deleted", False),
            ("literal_split_changes_content", "User <*> not found", "User <*> not <*>", False),
        ]
    )
    def test_fingerprint_matches_across_template_wobble(self, _name, a, b, expected_equal) -> None:
        assert (pattern_fingerprint(a) == pattern_fingerprint(b)) is expected_equal

    def test_all_placeholder_template_falls_back_to_raw_template(self) -> None:
        assert pattern_fingerprint("<*> <num>") == "<*> <num>"
        assert pattern_fingerprint("<*> <num>") != pattern_fingerprint("<*> <ip>")


class TestDiffPatterns(TestCase):
    def _diff(self, current, baseline, baseline_window=_BASELINE_HOUR):
        return diff_patterns(current, baseline, current_window=_HOUR, baseline_window=baseline_window)

    @parameterized.expand(
        [
            # (name, share, severities, expected_classification)
            ("above_share_floor", 5.0, {"info": 50}, "new"),
            ("below_floor_with_errors", 0.2, {"error": 2}, "new"),
            ("below_floor_info_no_claim", 0.2, {"info": 2}, "unchanged"),
        ]
    )
    def test_novelty_floor(self, _name, share, severities, expected) -> None:
        entries = self._diff([_pattern("fresh template here", count=2, share=share, severities=severities)], [])
        assert entries[0]["classification"] == expected

    @parameterized.expand(
        [
            # (name, current_count, baseline_count, expected_classification, expected_ratio)
            ("doubled", 100, 50, "rate_shift", 2.0),
            ("halved", 50, 100, "rate_shift", 0.5),
            ("within_band", 60, 50, "unchanged", 1.2),
        ]
    )
    def test_rate_shift_thresholds(self, _name, cur, base, expected, ratio) -> None:
        entries = self._diff([_pattern("api call took long", count=cur)], [_pattern("api call took long", count=base)])
        assert entries[0]["classification"] == expected
        assert entries[0]["rate_ratio"] == ratio
        assert entries[0]["baseline_estimated_count"] == base

    def test_shift_needs_enough_samples_on_both_sides(self) -> None:
        # A 4x ratio built on 4 baseline samples is sampling noise, not a claim.
        entries = self._diff([_pattern("rare thing", count=16)], [_pattern("rare thing", count=4)])
        assert entries[0]["classification"] == "unchanged"

    def test_rates_are_normalized_by_window_length(self) -> None:
        # Same estimated count over half the window time = 2x the rate: dropping the
        # normalization would make any unequal-window comparison misclassify.
        entries = self._diff(
            [_pattern("steady heartbeat msg", count=100)],
            [_pattern("steady heartbeat msg", count=100)],
            baseline_window=_BASELINE_TWO_HOURS,
        )
        assert entries[0]["classification"] == "rate_shift"
        assert entries[0]["rate_ratio"] == 2.0

    @parameterized.expand(
        [
            ("above_floor_reported", 5.0, {"info": 50}, ["gone"]),
            ("below_floor_dropped_entirely", 0.2, {"info": 2}, []),
        ]
    )
    def test_gone(self, _name, share, severities, expected_classifications) -> None:
        entries = self._diff([], [_pattern("old template gone", count=2, share=share, severities=severities)])
        assert [e["classification"] for e in entries] == expected_classifications

    def test_wobbled_templates_merge_via_fingerprint_instead_of_new_plus_gone(self) -> None:
        # The same message mined as different placeholder kinds across runs must compare as
        # one pattern — matching on raw template strings would report a false new+gone pair.
        entries = self._diff(
            [_pattern("User <*> not found", count=100)],
            [_pattern("User <num> not found", count=50)],
        )
        assert [e["classification"] for e in entries] == ["rate_shift"]

    def test_within_run_template_splits_are_aggregated_before_classification(self) -> None:
        # Two below-floor fragments of one message must combine (2 x 0.6% = 1.2% > floor)
        # into a single entry classified on their summed counts.
        entries = self._diff(
            [
                _pattern("connect to <ip> failed", count=3, share=0.6),
                _pattern("connect to <*> failed", count=2, share=0.6),
            ],
            [],
        )
        assert len(entries) == 1
        assert entries[0]["classification"] == "new"
        assert entries[0]["pattern"]["pattern"] == "connect to <ip> failed"

    def test_error_severity_on_a_non_representative_group_member_still_clears_the_floor(self) -> None:
        # A below-floor group whose largest (representative) template is info but which contains a
        # smaller error-severity template must surface as "new": the error line is the whole point.
        entries = self._diff(
            [
                _pattern("connect to <ip> failed", count=3, share=0.4, severities={"info": 3}),
                _pattern("connect to <*> failed", count=2, share=0.4, severities={"error": 2}),
            ],
            [],
        )
        assert len(entries) == 1
        assert entries[0]["classification"] == "new"

    def test_entries_ordered_by_interest(self) -> None:
        entries = self._diff(
            [
                _pattern("boring stable msg", count=50),
                _pattern("brand new failure", count=30, share=30.0),
                _pattern("spiking msg here", count=200),
            ],
            [
                _pattern("boring stable msg", count=50),
                _pattern("spiking msg here", count=50),
                _pattern("vanished template msg", count=50, share=50.0),
            ],
        )
        assert [e["classification"] for e in entries] == ["new", "rate_shift", "gone", "unchanged"]


_FROZEN_NOW = "2026-06-23T13:00:00Z"


class TestRunPatternsDiff(ClickhouseTestMixin, APIBaseTest):
    def _insert(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

    def _log(self, body: str, *, day: int, severity: str = "info", service: str = "api", minute: int = 0) -> dict:
        return {
            "timestamp": f"2026-06-{day:02d} 12:{minute:02d}:00.000000",
            "body": body,
            "severity_text": severity,
            "service_name": service,
        }

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_auto_baseline_mines_the_same_window_a_week_earlier(self) -> None:
        # Wiring no pure test can catch: the baseline window must be the resolved current
        # window shifted -7d, with the query's filters carried over, and the whole diff
        # deterministic across reruns.
        current = [self._log(f"User {name} not found", day=23, severity="error") for name in ("alice", "bob", "carol")]
        baseline = [self._log(f"GET /api/orders/{i} ok", day=16) for i in range(3)]
        other_service = [
            self._log("ignore me entirely", day=23, service="db"),
            *[self._log("ignore me entirely", day=16, service="db") for _ in range(2)],
        ]
        self._insert(current + baseline + other_service)

        query = LogsQuery(
            dateRange=DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z"),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=["api"],
            searchTerm=None,
        )

        results = run_patterns_diff(self.team, query, None)

        by_classification = {e["classification"]: e for e in results["entries"]}
        assert by_classification["new"]["pattern"]["pattern"] == "User <*> not found"
        assert by_classification["gone"]["pattern"]["pattern"] == "GET /api/orders/<num> ok"
        # The serviceNames filter reached both windows: the "db" rows appear in neither.
        assert len(results["entries"]) == 2
        assert results["current"]["total_count"] == 3
        assert results["baseline"]["total_count"] == 3
        assert results["baseline"]["date_from"].startswith("2026-06-16T12:00:00")
        assert results["baseline"]["date_to"].startswith("2026-06-16T13:00:00")

        assert run_patterns_diff(self.team, query, None) == results

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_explicit_baseline_range_is_used_verbatim(self) -> None:
        self._insert(
            [
                self._log("deploy marker line", day=23),
                self._log("deploy marker line", day=20),
                self._log("other thing", day=20),
            ]
        )

        query = LogsQuery(
            dateRange=DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z"),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[],
            searchTerm=None,
        )
        baseline = DateRange(date_from="2026-06-20T12:00:00Z", date_to="2026-06-20T13:00:00Z")

        results = run_patterns_diff(self.team, query, baseline)

        assert results["baseline"]["date_from"].startswith("2026-06-20T12:00:00")
        assert results["baseline"]["total_count"] == 2

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_both_windows_share_one_deadline(self) -> None:
        self._insert([self._log("deploy marker line", day=23), self._log("deploy marker line", day=16)])
        query = LogsQuery(
            dateRange=DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z"),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[],
            searchTerm=None,
        )

        with patch("products.logs.backend.patterns_query_runner.monotonic", return_value=100.0) as clock:
            budgets = []

            def execute_with_elapsed_time(*args, **kwargs):
                budgets.append(kwargs["settings"].max_execution_time)
                result = execute_hogql_query(*args, **kwargs)
                clock.return_value += 200
                return result

            with patch(
                "products.logs.backend.patterns_query_runner.execute_hogql_query",
                side_effect=execute_with_elapsed_time,
            ):
                # Three timeouts in a row would open the query failure breaker if they counted.
                for _ in range(3):
                    budgets.clear()
                    with self.assertRaises(ClickHouseQueryTimeOut):
                        run_patterns_diff(self.team, query, None, deadline=clock.return_value + 420)
                    # Two queries per window. The third query gets the 20 seconds left, and no query gets
                    # more than its own 60-second limit.
                    assert budgets == [60, 60, 20]

                results = run_patterns_diff(self.team, query, None)

        assert results["baseline"]["total_count"] == 1


class TestStoredPatternKeys(TestCase):
    def test_groups_sharing_a_stored_member_compare_as_one_pattern(self) -> None:
        current = [
            {
                **_pattern("Retry <*> timed out", count=100),
                "match_patterns": ["Retry <N> timed out", "Retry <N> timed out again"],
            }
        ]
        baseline = [{**_pattern("Retry <N> timed out", count=50), "match_patterns": ["Retry <N> timed out"]}]

        keys = stored_pattern_keys(current, baseline)
        entries = diff_patterns(current, baseline, current_window=_HOUR, baseline_window=_BASELINE_HOUR, key=keys)

        assert [e["classification"] for e in entries] == ["rate_shift"]

    def test_a_baseline_group_spanning_two_current_groups_matches_both(self) -> None:
        current = [
            {**_pattern("Retry <*> timed out", count=100), "match_patterns": ["Retry <N> timed out"]},
            {**_pattern("Retry <*> timed out again", count=100), "match_patterns": ["Retry <N> timed out again"]},
        ]
        baseline = [
            {
                **_pattern("Retry <*> timed out", count=100),
                "match_patterns": ["Retry <N> timed out again", "Retry <N> timed out"],
            }
        ]

        keys = stored_pattern_keys(current, baseline)
        entries = diff_patterns(current, baseline, current_window=_HOUR, baseline_window=_BASELINE_HOUR, key=keys)

        assert "new" not in [e["classification"] for e in entries]


def _bare_query() -> LogsQuery:
    return LogsQuery(
        dateRange=DateRange(date_from="-1h"),
        filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
        severityLevels=[],
        serviceNames=[],
    )


class TestRawLinesCall(TestCase):
    _WINDOW = (dt.datetime(2026, 6, 23, 12, 0, tzinfo=dt.UTC), dt.datetime(2026, 6, 23, 13, 0, tzinfo=dt.UTC))

    def _entry(self, **pattern: Any) -> dict:
        return {"classification": "new", "masked_example": "boom <*>", "services": ["api"], "pattern": pattern}

    def test_keeps_the_original_scope_and_adds_the_pattern(self) -> None:
        query = LogsQuery(
            dateRange=DateRange(date_from="-1h"),
            serviceNames=[],
            severityLevels=["error"],
            searchTerm="checkout",
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(key="env", value="prod", operator=PropertyOperator.EXACT, type="log")
                        ],
                    )
                ],
            ),
        )

        call = _raw_lines_call(self._entry(match_regex="boom .*"), query, *self._WINDOW)

        assert call is not None
        assert call["query"]["severityLevels"] == ["error"]
        assert call["query"]["searchTerm"] == "checkout"
        assert [f["key"] for f in call["query"]["filterGroup"]] == ["env", "message"]

    def test_omits_the_call_without_a_matcher(self) -> None:
        query = _bare_query()

        assert _raw_lines_call(self._entry(match_regex=None, match_literal=""), query, *self._WINDOW) is None


class TestFirstSeenEver(TestCase):
    _ENTRIES = [{"pattern": {"match_patterns": [f"pattern {i}" for i in range(150)]}}]

    def test_sets_an_explicit_limit_for_every_member(self) -> None:
        with patch("products.logs.backend.pattern_diff.execute_hogql_query") as execute:
            execute.return_value.results = []
            _first_seen_ever(MagicMock(), _bare_query(), self._ENTRIES, 1, dt.datetime.now(dt.UTC))

        assert execute.call_args.kwargs["query"].limit.value == 150

    def test_returns_none_when_the_history_lookup_hits_its_budget(self) -> None:
        with patch(
            "products.logs.backend.pattern_diff.execute_hogql_query", side_effect=CHQueryErrorTooManyBytes("too many")
        ):
            result = _first_seen_ever(MagicMock(), _bare_query(), self._ENTRIES, 1, dt.datetime.now(dt.UTC))

        assert result is None

    @parameterized.expand([("time_left", 110.0, 10), ("deadline_passed", 100.5, None)])
    def test_stays_inside_the_request_deadline(self, _name, deadline, expected_limit) -> None:
        with (
            patch("products.logs.backend.pattern_diff.monotonic", return_value=100.0),
            patch("products.logs.backend.pattern_diff.execute_hogql_query") as execute,
        ):
            execute.return_value.results = []
            _first_seen_ever(MagicMock(), _bare_query(), self._ENTRIES, 1, dt.datetime.now(dt.UTC), deadline)

        if expected_limit is None:
            execute.assert_not_called()
        else:
            assert execute.call_args.kwargs["settings"].max_execution_time == expected_limit


class TestRunPatternsDiffV2(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _insert(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

    def _log(
        self,
        body: str,
        *,
        day: int,
        severity: str = "info",
        service: str = "api",
        minute: int = 0,
        stored: str | None = None,
    ) -> dict:
        row: dict[str, str | int] = {
            "timestamp": f"2026-06-{day:02d} 12:{minute:02d}:00.000000",
            "body": body,
            "severity_text": severity,
            "service_name": service,
        }
        if stored is not None:
            row.update({"pattern": stored, "pattern_version": 5})
        return row

    def _query(self, severity_levels: list[str] | None = None) -> LogsQuery:
        return LogsQuery(
            dateRange=DateRange(date_from="2026-06-23T12:00:00Z", date_to="2026-06-23T13:00:00Z"),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=severity_levels or [],
            serviceNames=[],
            searchTerm=None,
        )

    def _seed_stored(self, *, stamp_baseline: bool = True) -> None:
        retry = [
            self._log(
                f"Retry {i} timed out",
                day=23,
                severity="error",
                service="worker",
                minute=i,
                stored="Retry <N> timed out",
            )
            for i in range(3)
        ]
        archive_current = [
            self._log(f"Archive job run_{i} queued", day=23, minute=i, stored="Archive job <ID> queued")
            for i in range(3)
        ]
        archive_baseline = [
            self._log(
                f"Archive job run_{i} queued",
                day=16,
                minute=i,
                stored="Archive job <ID> queued" if stamp_baseline else None,
            )
            for i in range(3)
        ]
        archive_history = [self._log("Archive job run_old queued", day=12, stored="Archive job <ID> queued")]
        rows = retry + archive_current + archive_baseline + archive_history
        self._insert(rows)
        # The test `logs` table feeds no pattern rollup, so write the rows its materialized view would.
        rollup = "".join(
            json.dumps(
                {
                    "team_id": self.team.id,
                    "time_bucket": row["timestamp"][:15] + "0:00",
                    "service_name": row["service_name"],
                    "severity_text": row["severity_text"],
                    "pattern_version": 5,
                    "pattern": row["pattern"],
                    "log_count": 1,
                }
            )
            + "\n"
            for row in rows
            if "pattern" in row
        )
        sync_execute(f"INSERT INTO logs_pattern_buckets FORMAT JSONEachRow\n{rollup}")

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_stored_patterns_are_used_when_both_windows_are_covered(self) -> None:
        self._seed_stored()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            results = run_patterns_diff(self.team, self._query(), None)

        assert results["source"] == "stored_patterns"
        assert results["pattern_version"] == 5
        assert results["sampled"] is False
        assert results["current"]["source"] == results["baseline"]["source"] == "stored_patterns"
        by_example = {e["masked_example"]: e for e in results["entries"]}
        retry = by_example["Retry <N> timed out"]
        assert retry["classification"] == "new"
        assert retry["services"] == ["worker"]
        assert retry["first_seen_ever"] == "2026-06-23T12:00:00Z"
        archive = by_example["Archive job <ID> queued"]
        assert archive["classification"] == "unchanged"
        assert archive["first_seen_ever"] == "2026-06-12T12:00:00Z"

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_the_version_check_shares_the_runner_time_budget(self) -> None:
        self._seed_stored(stamp_baseline=False)
        clock = iter([0.0, 0.0] + [1000.0] * 100)

        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch("products.logs.backend.patterns_query_runner.monotonic", side_effect=lambda: next(clock)),
            self.assertRaises(ClickHouseQueryTimeOut),
        ):
            run_patterns_diff(self.team, self._query(), None)

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_partial_coverage_falls_back_to_body_mining_in_both_windows(self) -> None:
        self._seed_stored(stamp_baseline=False)

        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch.object(PatternsQueryRunner, "_calculate_stored_patterns", side_effect=AssertionError),
            patch.object(PatternsQueryRunner, "_count", side_effect=AssertionError),
            patch("products.logs.backend.patterns_query_runner.app_org_concurrency_slot") as slot,
        ):
            results = run_patterns_diff(self.team, self._query(), None)

        assert slot.call_count == 2

        assert results["source"] == "body_mining"
        assert results["sampled"] is True
        assert results["current"]["source"] == results["baseline"]["source"] == "body_mining"
        assert sorted(e["classification"] for e in results["entries"]) == ["new", "unchanged"]
        assert all(e["first_seen_ever"] is None for e in results["entries"])
        assert any("first_seen_ever" in note for note in results["notes"])

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_body_mining_entries_carry_masked_examples_and_pivots(self) -> None:
        self._insert(
            [self._log(f"User {name} not found", day=23, severity="error") for name in ("alice", "bob", "carol")]
        )

        plain = run_patterns_diff(self.team, self._query(), None)

        entry = plain["entries"][0]
        assert entry["masked_example"] == "User <*> not found"
        assert entry["services"] == ["api"]
        assert plain["window"] == {
            "current": {"from": "2026-06-23T12:00:00Z", "to": "2026-06-23T13:00:00Z"},
            "baseline": {"from": "2026-06-16T12:00:00Z", "to": "2026-06-16T13:00:00Z"},
            "timezone": "UTC",
        }
        assert plain["next"][0]["tool"] == "query-logs"
        assert plain["next"][0]["query"]["filterGroup"][0]["operator"] == "regex"

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_severity_levels_scope_both_windows(self) -> None:
        self._insert(
            [
                self._log("disk almost full", day=23, severity="warn"),
                self._log("heartbeat ok", day=23),
                self._log("heartbeat ok", day=16),
            ]
        )

        results = run_patterns_diff(self.team, self._query(["warn", "error", "fatal"]), None)

        assert [e["masked_example"] for e in results["entries"]] == ["disk almost full"]
        assert results["baseline"]["total_count"] == 0

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_limit_truncates_entries(self) -> None:
        self._insert([self._log("first new thing", day=23), self._log("second new thing", day=23)])

        results = run_patterns_diff(self.team, self._query(), None, limit=1)

        assert len(results["entries"]) == 1
        assert results["truncated"] is True


class TestPatternsDiffAPIV2(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @time_machine.travel(_FROZEN_NOW, tick=False)
    def test_endpoint_accepts_limit(self) -> None:
        sql = "".join(
            json.dumps(
                {
                    "team_id": self.team.id,
                    "timestamp": f"2026-06-23 12:0{i}:00.000000",
                    "body": body,
                    "severity_text": "error",
                    "service_name": "api",
                }
            )
            + "\n"
            for i, body in enumerate(["socket closed by peer", "queue overflow detected"])
        )
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/patterns_diff/",
            {
                "query": {
                    "dateRange": {"date_from": "2026-06-23T12:00:00Z", "date_to": "2026-06-23T13:00:00Z"},
                    "severityLevels": ["error"],
                    "limit": 1,
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert len(body["entries"]) == 1
        assert body["truncated"] is True
        assert body["sampled"] is True
        assert body["window"]["timezone"] == "UTC"
