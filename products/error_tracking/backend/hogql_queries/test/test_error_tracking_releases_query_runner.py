from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DateRange,
    ErrorTrackingReleasesOrderBy,
    ErrorTrackingReleasesQuery,
    ErrorTrackingReleasesQueryResponse,
)

from products.error_tracking.backend.hogql_queries.error_tracking_releases_query_runner import (
    MAX_QUERY_RELEASES,
    MAX_RELEASES,
    MAX_RESOLUTION,
    ErrorTrackingReleasesQueryRunner,
    version_tuple,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

ISSUE_ID = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
OTHER_ISSUE_ID = "01936e7f-d7ff-7314-b2d4-7627981e34f1"


class TestErrorTrackingReleasesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_issue(self, issue_id: str, fingerprints: list[str]) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(id=issue_id, team=self.team)
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def create_exception(
        self, fingerprint: str, timestamp: str, release: tuple[str, str | None, str | None] | None
    ) -> None:
        properties: dict = {"$exception_fingerprint": fingerprint}
        if release:
            namespace, version, build = release
            properties["$app_namespace"] = namespace
            if version is not None:
                properties["$app_version"] = version
            if build is not None:
                properties["$app_build"] = build
        _create_event(
            distinct_id="user", event="$exception", team=self.team, timestamp=timestamp, properties=properties
        )

    def run_query(self, **kwargs) -> ErrorTrackingReleasesQueryResponse:
        query = ErrorTrackingReleasesQuery(
            kind="ErrorTrackingReleasesQuery",
            issueId=ISSUE_ID,
            dateRange=DateRange(date_from="2024-01-01T00:00:00Z", date_to="2024-01-08T00:00:00Z"),
            resolution=7,
            **kwargs,
        )
        return ErrorTrackingReleasesQueryRunner(team=self.team, query=query).calculate()

    @freeze_time("2024-01-10T12:00:00Z")
    def test_folds_releases_across_merged_fingerprints(self) -> None:
        self.create_issue(ISSUE_ID, ["fp-a", "fp-b"])
        self.create_issue(OTHER_ISSUE_ID, ["fp-other"])
        ios = ("com.example.ios", "2.9.0", "1502")
        old_ios = ("com.example.ios", "2.8.0", "1460")
        android = ("com.example.android", "2.9.0", "20901")
        for fingerprint, day, release in [
            ("fp-a", 1, old_ios),
            ("fp-b", 2, old_ios),
            ("fp-a", 4, ios),
            ("fp-b", 4, ios),
            ("fp-a", 5, ios),
            ("fp-a", 5, android),
            ("fp-a", 3, None),
            ("fp-other", 4, ios),
        ]:
            self.create_exception(fingerprint, f"2024-01-0{day}T10:00:00Z", release)
        flush_persons_and_events()

        response = self.run_query(maxReleases=2)

        assert response.bucket_seconds == 24 * 60 * 60
        assert len(response.buckets) == 7
        # Newest first appearance on top.
        assert [(r.namespace, r.version, r.build, r.total) for r in response.results] == [
            ("com.example.android", "2.9.0", "20901", 1),
            ("com.example.ios", "2.9.0", "1502", 3),
        ]
        assert response.results[1].counts == [0, 0, 0, 2, 1, 0, 0]
        assert response.results[1].first_seen == "2024-01-04T00:00:00+00:00"
        assert response.results[1].last_seen == "2024-01-05T00:00:00+00:00"
        assert response.other is not None
        assert response.other.counts == [1, 1, 0, 0, 0, 0, 0]
        assert response.other_release_count == 1
        assert response.unattributed is not None
        assert response.unattributed.total == 1
        assert response.release_count == 3
        assert response.namespaces == ["com.example.android", "com.example.ios"]
        assert response.total == 7

    @freeze_time("2024-01-10T12:00:00Z")
    def test_app_namespace_filter_and_occurrence_order(self) -> None:
        self.create_issue(ISSUE_ID, ["fp-a"])
        for release, count in [
            (("com.example.ios", "2.9.1", "1507"), 1),
            (("com.example.ios", "2.8.0", "1460"), 3),
            (("com.example.android", "2.9.0", "20901"), 2),
        ]:
            for _ in range(count):
                self.create_exception("fp-a", "2024-01-04T10:00:00Z", release)
        self.create_exception("fp-a", "2024-01-04T10:00:00Z", None)
        flush_persons_and_events()

        response = self.run_query(appNamespace="com.example.ios", orderBy=ErrorTrackingReleasesOrderBy.OCCURRENCES)

        assert [(r.version, r.total) for r in response.results] == [("2.8.0", 3), ("2.9.1", 1)]
        assert response.unattributed is None
        assert response.release_count == 2
        assert response.namespaces == ["com.example.android", "com.example.ios"]
        assert response.total == 4

    @freeze_time("2024-01-10T12:00:00Z")
    def test_latest_orders_by_first_seen_then_version(self) -> None:
        self.create_issue(ISSUE_ID, ["fp-a"])
        for day, release in [
            (1, ("com.example.ios", "3.0.0", "1600")),
            (1, ("com.example.ios", "2.9.0", "1502")),
            (2, ("com.example.ios", None, None)),
            (3, ("com.example.ios", "3a1b2c", None)),
            (4, ("com.example.ios", "2.8.0", "1460")),
        ]:
            self.create_exception("fp-a", f"2024-01-0{day}T10:00:00Z", release)
        flush_persons_and_events()

        response = self.run_query()

        # An old release that reappears late ranks first, and a hash orders like any other version.
        # Releases that share a first bucket order by version number. Unversioned releases sort last.
        assert [r.version for r in response.results] == ["2.8.0", "3a1b2c", "3.0.0", "2.9.0", None]

    @freeze_time("2024-01-10T12:00:00Z")
    def test_counts_an_event_at_the_inclusive_range_end(self) -> None:
        self.create_issue(ISSUE_ID, ["fp-a"])
        self.create_exception("fp-a", "2024-01-08T00:00:00Z", ("com.example.ios", "3.0.0", "1600"))
        flush_persons_and_events()

        response = self.run_query()

        assert response.results[0].counts == [0, 0, 0, 0, 0, 0, 1]
        assert response.total == 1

    @parameterized.expand([(10**9, MAX_RESOLUTION + 1), (-1, 2)])
    def test_clamps_resolution(self, resolution: int, max_bucket_count: int) -> None:
        runner = ErrorTrackingReleasesQueryRunner(
            team=self.team,
            query=ErrorTrackingReleasesQuery(
                kind="ErrorTrackingReleasesQuery",
                issueId=ISSUE_ID,
                dateRange=DateRange(date_from="2024-01-01T00:00:00Z", date_to="2024-01-08T00:00:00Z"),
                resolution=resolution,
            ),
        )

        assert 1 <= len(runner.bucket_starts) <= max_bucket_count

    def test_caps_max_releases(self) -> None:
        runner = ErrorTrackingReleasesQueryRunner(
            team=self.team,
            query=ErrorTrackingReleasesQuery(
                kind="ErrorTrackingReleasesQuery",
                issueId=ISSUE_ID,
                dateRange=DateRange(date_from="2024-01-01T00:00:00Z", date_to="2024-01-08T00:00:00Z"),
                resolution=7,
                maxReleases=10**6,
            ),
        )
        bucket = runner.bucket_starts[-1]
        rows = [("com.example.ios", str(i), None, [(bucket, 1)], 1) for i in range(MAX_RELEASES + 1)]

        response = runner.fold(rows)

        assert len(response.results) == MAX_RELEASES
        assert response.other_release_count == 1
        assert response.other is not None
        assert response.other.counts == [0, 0, 0, 0, 0, 0, 1]

    def test_flags_a_release_count_the_query_capped(self) -> None:
        runner = ErrorTrackingReleasesQueryRunner(
            team=self.team,
            query=ErrorTrackingReleasesQuery(
                kind="ErrorTrackingReleasesQuery",
                issueId=ISSUE_ID,
                dateRange=DateRange(date_from="2024-01-01T00:00:00Z", date_to="2024-01-08T00:00:00Z"),
                resolution=7,
            ),
        )
        bucket = runner.bucket_starts[-1]

        def rows(count: int) -> list:
            return [("com.example.ios", str(index), None, [(bucket, 1)], 1) for index in range(count)]

        assert runner.fold(rows(MAX_QUERY_RELEASES)).release_count_truncated is True
        assert runner.fold(rows(MAX_QUERY_RELEASES - 1)).release_count_truncated is False

    def test_rejects_malformed_issue_id(self) -> None:
        with self.assertRaises(ValidationError):
            ErrorTrackingReleasesQueryRunner(
                team=self.team,
                query=ErrorTrackingReleasesQuery(kind="ErrorTrackingReleasesQuery", issueId="not-a-uuid"),
            )


def test_version_tuple_bounds_digit_runs() -> None:
    assert version_tuple("1" * 5000 + ".2") == (int("1" * 18),)
