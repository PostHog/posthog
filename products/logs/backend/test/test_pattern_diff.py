import json
import datetime as dt

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import TestCase

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.clickhouse.client import sync_execute

from products.logs.backend.log_patterns import pattern_fingerprint
from products.logs.backend.pattern_diff import diff_patterns, run_patterns_diff

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

    @freeze_time(_FROZEN_NOW)
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

    @freeze_time(_FROZEN_NOW)
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
