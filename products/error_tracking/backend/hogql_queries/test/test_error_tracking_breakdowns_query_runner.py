from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import DateRange, ErrorTrackingBreakdownsQuery

from products.error_tracking.backend.hogql_queries.error_tracking_breakdowns_query_runner import (
    ErrorTrackingBreakdownsQueryRunner,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2


class TestErrorTrackingBreakdownsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    issue_id = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
    fingerprint = "test_fingerprint"

    def create_issue(self, issue_id, fingerprint):
        issue = ErrorTrackingIssue.objects.create(id=issue_id, team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def create_exception_event(self, distinct_id, properties):
        base_properties = {
            "$exception_issue_id": self.issue_id,
            "$exception_fingerprint": self.fingerprint,
        }
        _create_event(
            distinct_id=distinct_id,
            event="$exception",
            team=self.team,
            properties={**base_properties, **properties},
        )

    @freeze_time("2024-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_breakdown_with_limit(self):
        self.create_issue(self.issue_id, self.fingerprint)

        browsers = [("A", 10), ("B", 8), ("C", 6), ("D", 4), ("E", 2), ("F", 1)]
        for browser, count in browsers:
            for _ in range(count):
                self.create_exception_event(f"user_{browser}", {"$browser": browser})

        flush_persons_and_events()

        runner = ErrorTrackingBreakdownsQueryRunner(
            team=self.team,
            query=ErrorTrackingBreakdownsQuery(
                kind="ErrorTrackingBreakdownsQuery",
                issueId=self.issue_id,
                breakdownProperties=["$browser"],
                dateRange=DateRange(date_from="-7d"),
                maxValuesPerProperty=3,
            ),
        )

        response = runner.calculate()

        browser_data = response.results["$browser"]

        assert len(browser_data.values) == 3
        assert browser_data.total_count == 31

        assert browser_data.values[0].value == "A"
        assert browser_data.values[0].count == 10
        assert browser_data.values[1].value == "B"
        assert browser_data.values[1].count == 8
        assert browser_data.values[2].value == "C"
        assert browser_data.values[2].count == 6

    @freeze_time("2024-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_multiple_breakdown_properties(self):
        self.create_issue(self.issue_id, self.fingerprint)

        for _ in range(5):
            self.create_exception_event("user_1", {"$browser": "Chrome", "$os": "Windows"})
        for _ in range(3):
            self.create_exception_event("user_2", {"$browser": "Firefox", "$os": "macOS"})
        for _ in range(2):
            self.create_exception_event("user_3", {"$browser": "Safari", "$os": "macOS"})

        flush_persons_and_events()

        runner = ErrorTrackingBreakdownsQueryRunner(
            team=self.team,
            query=ErrorTrackingBreakdownsQuery(
                kind="ErrorTrackingBreakdownsQuery",
                issueId=self.issue_id,
                breakdownProperties=["$browser", "$os"],
                dateRange=DateRange(date_from="-7d"),
                maxValuesPerProperty=3,
            ),
        )

        response = runner.calculate()

        assert "$browser" in response.results
        assert "$os" in response.results

        browser_data = response.results["$browser"]
        assert len(browser_data.values) == 3
        assert browser_data.total_count == 10
        assert browser_data.values[0].value == "Chrome"
        assert browser_data.values[0].count == 5

        os_data = response.results["$os"]
        assert len(os_data.values) == 2
        assert os_data.total_count == 10
        assert os_data.values[0].value == "macOS"
        assert os_data.values[0].count == 5
        assert os_data.values[1].value == "Windows"
        assert os_data.values[1].count == 5

    @freeze_time("2024-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_breakdown_with_null_values(self):
        self.create_issue(self.issue_id, self.fingerprint)

        for _ in range(5):
            self.create_exception_event("user_1", {"$browser": "Chrome"})
        for _ in range(3):
            self.create_exception_event("user_2", {})

        flush_persons_and_events()

        runner = ErrorTrackingBreakdownsQueryRunner(
            team=self.team,
            query=ErrorTrackingBreakdownsQuery(
                kind="ErrorTrackingBreakdownsQuery",
                issueId=self.issue_id,
                breakdownProperties=["$browser"],
                dateRange=DateRange(date_from="-7d"),
                maxValuesPerProperty=3,
            ),
        )

        response = runner.calculate()

        browser_data = response.results["$browser"]
        assert len(browser_data.values) == 2
        assert browser_data.total_count == 8

        assert browser_data.values[0].value == "Chrome"
        assert browser_data.values[0].count == 5

        assert browser_data.values[1].value == "$$_posthog_breakdown_null_$$"
        assert browser_data.values[1].count == 3

    @freeze_time("2024-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_breakdown_respects_date_range(self):
        self.create_issue(self.issue_id, self.fingerprint)

        # outside range
        with freeze_time("2024-01-01T12:00:00Z"):
            for _ in range(10):
                self.create_exception_event("user_old", {"$browser": "OldBrowser"})

        # within range
        for _ in range(5):
            self.create_exception_event("user_1", {"$browser": "Chrome"})

        flush_persons_and_events()

        runner = ErrorTrackingBreakdownsQueryRunner(
            team=self.team,
            query=ErrorTrackingBreakdownsQuery(
                kind="ErrorTrackingBreakdownsQuery",
                issueId=self.issue_id,
                breakdownProperties=["$browser"],
                dateRange=DateRange(date_from="-7d"),
                maxValuesPerProperty=3,
            ),
        )

        response = runner.calculate()

        browser_data = response.results["$browser"]

        assert len(browser_data.values) == 1
        assert browser_data.total_count == 5
        assert browser_data.values[0].value == "Chrome"
        assert browser_data.values[0].count == 5
