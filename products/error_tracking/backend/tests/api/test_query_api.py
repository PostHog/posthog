from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags

from products.error_tracking.backend.facade.query_utils import (
    build_fingerprint_event_where,
    build_issue_filters,
    build_search_query,
    build_sparkline,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


class FakeQueryResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def model_dump(self, *, mode: str = "json") -> dict[str, object]:
        return self.data


def test_issue_event_search_escapes_like_wildcards_and_quotes() -> None:
    where = build_fingerprint_event_where(["fingerprint"], r"a%_'\\")[1]

    assert r"\%" in where
    assert r"\_" in where
    assert r"\'" in where
    assert r"\\" in where


def test_search_query_preserves_quotes() -> None:
    assert build_search_query({"searchQuery": "can't read property"}) == "can't read property"
    assert build_search_query({"searchQuery": '"cannot read"', "filePath": "src/app.ts"}) == '"cannot read" src/app.ts'


def test_release_filter_adds_substring_prefilter() -> None:
    filters = build_issue_filters({"release": "2026.04.24"})

    assert filters[0] == {
        "type": "hogql",
        "key": "position(toString(properties.$exception_releases), '2026.04.24') > 0",
    }
    assert "JSONExtractKeysAndValuesRaw" in str(filters[1]["key"])


def test_build_sparkline_accepts_float_values() -> None:
    assert build_sparkline({"aggregations": {"volumeRange": [1.0, 2.5]}}) == [1.0, 2.5]


class TestErrorTrackingQueryAPI(ClickhouseTestMixin, APIBaseTest):
    issue_id = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
    fingerprint = "issue-fingerprint"

    @classmethod
    def setUpClass(cls) -> None:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize

        if ("$exception_issue_id", "properties") not in get_materialized_columns("events"):
            materialize("events", "$exception_issue_id", is_nullable=True)
        super().setUpClass()

    def setUp(self) -> None:
        super().setUp()
        _create_person(team=self.team, distinct_ids=["user-1"], is_identified=True)
        flush_persons_and_events()

    def create_issue(self, issue_id: str | None = None, fingerprint: str | None = None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(id=issue_id or self.issue_id, team=self.team, name="TypeError")
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=issue, fingerprint=fingerprint or self.fingerprint
        )
        # the query always uses the denormalized ClickHouse table, so mirror the issue state there
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def create_exception_event(
        self,
        *,
        issue_id: str | None = None,
        fingerprint: str | None = None,
        include_issue_id: bool = True,
        properties: dict[str, object] | None = None,
    ) -> None:
        resolved_issue_id = issue_id or self.issue_id
        resolved_fingerprint = fingerprint or self.fingerprint
        event_properties = {
            "$exception_fingerprint": resolved_fingerprint,
            "$exception_types": ["TypeError"],
            "$exception_values": ["Cannot read properties of undefined"],
            **(properties or {}),
        }
        if include_issue_id:
            event_properties["$exception_issue_id"] = resolved_issue_id
        _create_event(
            distinct_id="user-1",
            event="$exception",
            team=self.team,
            properties=event_properties,
            timestamp=now() - relativedelta(hours=1),
        )

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issues_list_accepts_typed_filters_and_matches_release_precisely(self) -> None:
        issue = self.create_issue()
        canonical_fingerprint = ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team,
            issue=issue,
            fingerprint="canonical-fingerprint-without-events",
        )
        ErrorTrackingIssueFingerprintV2.objects.filter(id=canonical_fingerprint.id).update(
            created_at=now() - timedelta(days=1)
        )
        self.create_exception_event(
            properties={
                "$lib": "posthog-js",
                "$browser": "Chrome",
                "$current_url": "https://example.test/checkout",
                "$exception_releases": {
                    "release-id-1": {
                        "version": "2026.04.24",
                        "project": "posthog-js",
                        "timestamp": "2026-04-24T10:00:00Z",
                        "metadata": {"git": {"commit_id": "commit-123", "branch": "main"}},
                    }
                },
            }
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/query/issues",
            data={
                "status": "all",
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "library": "posthog-js",
                "release": "2026.04.24",
                "fingerprint": self.fingerprint,
                "url": "/checkout",
                "filterGroup": [{"key": "$browser", "type": "event", "operator": "exact", "value": ["Chrome"]}],
            },
            format="json",
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [self.issue_id]
        assert response.json()["results"][0]["fingerprint"] == "canonical-fingerprint-without-events"

        project_response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/query/issues",
            data={
                "status": "all",
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "release": "posthog-js",
            },
            format="json",
        )

        assert project_response.status_code == 200
        assert project_response.json()["results"] == []

    def test_rejects_hogql_property_filters(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={"filterGroup": [{"key": "1 = 1", "type": "hogql", "value": "1"}]},
            format="json",
        )

        assert response.status_code == 400
        assert "HogQL property filters are not supported here" in str(response.json())

    def test_rejects_invalid_person_id(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={"personId": "not-a-uuid"},
            format="json",
        )

        assert response.status_code == 400

    def test_rejects_large_volume_resolution(self) -> None:
        list_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={"volumeResolution": 201},
            format="json",
        )
        detail_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "volumeResolution": 201},
            format="json",
        )

        assert list_response.status_code == 400
        assert detail_response.status_code == 400

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issues_list_filters_by_assignee(self) -> None:
        self.create_issue()
        self.create_exception_event()
        ErrorTrackingIssueAssignment.objects.create(issue_id=self.issue_id, user=self.user, team=self.team)
        # re-sync with a strictly newer version so the assignment wins argMax over the create-time row
        with freeze_time(now() + timedelta(seconds=1)):
            sync_issues_to_clickhouse(issue_ids=[self.issue_id], team_id=self.team.pk)
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={
                "status": "all",
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "assignee": {"type": "user", "id": self.user.pk},
            },
            format="json",
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [self.issue_id]

    def test_issues_list_tags_clickhouse_queries(self) -> None:
        observed_tags: list[tuple[object, object]] = []

        def calculate(_runner: object) -> FakeQueryResponse:
            tags = get_query_tags()
            observed_tags.append((tags.product, tags.feature))
            return FakeQueryResponse({"results": [], "hasMore": False, "limit": 25, "offset": 0})

        with patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate", calculate):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issues",
                data={"limit": 1},
                format="json",
            )

        assert response.status_code == 200
        assert observed_tags == [(Product.ERROR_TRACKING, Feature.QUERY)]

    def test_issues_list_normalizes_volume_resolution(self) -> None:
        observed_volume_resolutions: list[int] = []

        def calculate(runner: ErrorTrackingQueryRunner) -> FakeQueryResponse:
            observed_volume_resolutions.append(runner.query.volumeResolution)
            return FakeQueryResponse({"results": [], "hasMore": False, "limit": 25, "offset": 0})

        with patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate", calculate):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issues",
                data={"volumeResolution": 0},
                format="json",
            )

        assert response.status_code == 200
        assert observed_volume_resolutions == [1]

    def test_issue_detail_tags_clickhouse_queries(self) -> None:
        self.create_issue()
        observed_tags: list[tuple[object, object]] = []

        def calculate_issue(_runner: object) -> FakeQueryResponse:
            tags = get_query_tags()
            observed_tags.append((tags.product, tags.feature))
            return FakeQueryResponse(
                {
                    "results": [
                        {"id": self.issue_id, "name": "TypeError", "description": "Cannot read", "status": "active"}
                    ]
                }
            )

        def calculate_event(_runner: object) -> FakeQueryResponse:
            tags = get_query_tags()
            observed_tags.append((tags.product, tags.feature))
            return FakeQueryResponse({"columns": [], "results": []})

        with (
            patch(
                "products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate",
                calculate_issue,
            ),
            patch(
                "products.error_tracking.backend.presentation.views.query.EventsQueryRunner.calculate", calculate_event
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id},
                format="json",
            )

        assert response.status_code == 200
        assert observed_tags == [(Product.ERROR_TRACKING, Feature.QUERY), (Product.ERROR_TRACKING, Feature.QUERY)]

    def test_issue_detail_filters_by_fingerprint(self) -> None:
        self.create_issue()
        observed_volume_resolutions: list[int] = []
        observed_filter_groups: list[dict[str, object] | None] = []

        def calculate_issue(runner: ErrorTrackingQueryRunner) -> FakeQueryResponse:
            observed_volume_resolutions.append(runner.query.volumeResolution)
            observed_filter_groups.append(
                runner.query.filterGroup.model_dump(mode="json") if runner.query.filterGroup else None
            )
            return FakeQueryResponse(
                {
                    "results": [
                        {"id": self.issue_id, "name": "TypeError", "description": "Cannot read", "status": "active"}
                    ]
                }
            )

        def calculate_event(_runner: object) -> FakeQueryResponse:
            return FakeQueryResponse({"columns": [], "results": []})

        with (
            patch(
                "products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate",
                calculate_issue,
            ),
            patch(
                "products.error_tracking.backend.presentation.views.query.EventsQueryRunner.calculate", calculate_event
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id, "volumeResolution": 0},
                format="json",
            )

        assert response.status_code == 200
        assert observed_volume_resolutions == [1]
        assert observed_filter_groups[0] is not None
        assert "$exception_fingerprint" in str(observed_filter_groups[0])
        assert self.fingerprint in str(observed_filter_groups[0])

    def test_issue_detail_without_fingerprints_has_no_filter_group(self) -> None:
        ErrorTrackingIssue.objects.create(id=self.issue_id, team=self.team, name="TypeError")
        observed_filter_groups: list[dict[str, object] | None] = []

        def calculate_issue(runner: ErrorTrackingQueryRunner) -> FakeQueryResponse:
            observed_filter_groups.append(
                runner.query.filterGroup.model_dump(mode="json") if runner.query.filterGroup else None
            )
            return FakeQueryResponse(
                {
                    "results": [
                        {"id": self.issue_id, "name": "TypeError", "description": "Cannot read", "status": "active"}
                    ]
                }
            )

        def calculate_event(_runner: object) -> FakeQueryResponse:
            return FakeQueryResponse({"columns": [], "results": []})

        with (
            patch(
                "products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate",
                calculate_issue,
            ),
            patch(
                "products.error_tracking.backend.presentation.views.query.EventsQueryRunner.calculate", calculate_event
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id},
                format="json",
            )

        assert response.status_code == 200
        assert observed_filter_groups == [None]

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_detail_returns_impact_top_frame_and_latest_release(self) -> None:
        self.create_issue()
        self.create_exception_event(
            properties={
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read properties of undefined",
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "vendorLoad",
                                    "filename": "https://cdn.example.test/vendor.js",
                                    "lineno": 12,
                                    "colno": 3,
                                    "in_app": False,
                                },
                                {
                                    "function": "loadIssue",
                                    "filename": "https://example.test/app.js",
                                    "lineno": 42,
                                    "colno": 9,
                                    "in_app": True,
                                },
                            ]
                        },
                    }
                ],
                "$exception_releases": {
                    "release-id-1": {
                        "version": "2026.04.24",
                        "project": "posthog-js",
                        "timestamp": "2026-04-24T10:00:00Z",
                        "metadata": {"git": {"commit_id": "commit-123", "branch": "main"}},
                    }
                },
            }
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == self.issue_id
        assert data["impact"] == {"occurrences": 1, "users": 1, "sessions": 0}
        assert data["top_in_app_frame"] == {
            "function": "loadIssue",
            "source": "https://example.test/app.js",
            "line": 42,
            "column": 9,
            "in_app": True,
        }
        assert data["latest_release"]["version"] == "2026.04.24"
        assert data["latest_release"]["commit_id"] == "commit-123"

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_detail_returns_without_context_when_context_query_fails(self) -> None:
        self.create_issue()
        self.create_exception_event()
        flush_persons_and_events()

        with patch("products.error_tracking.backend.presentation.views.query.EventsQueryRunner") as events_query_runner:
            events_query_runner.side_effect = RuntimeError("boom")
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["id"] == self.issue_id
        assert "top_in_app_frame" not in response.json()

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_detail_distinguishes_missing_issue_from_empty_date_range(self) -> None:
        self.create_issue()

        empty_range_response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/query/issue",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "2026-04-23T00:00:00Z", "date_to": "2026-04-23T01:00:00Z"},
            },
            format="json",
        )
        missing_response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/query/issue",
            data={"issueId": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )

        assert empty_range_response.status_code == 200
        assert empty_range_response.json()["impact"] == {}
        assert empty_range_response.json()["fingerprint"] == self.fingerprint
        assert missing_response.status_code == 404

    def test_issue_events_returns_404_for_foreign_issue(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other_issue = ErrorTrackingIssue.objects.create(
            id="01936e80-7e11-7fd1-b0d1-f6f90c9b42bb", team=other_team, name="Other team issue"
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": str(other_issue.id)},
            format="json",
        )

        assert response.status_code == 404

    def test_issue_events_tags_clickhouse_queries(self) -> None:
        self.create_issue()
        observed_tags: list[tuple[object, object]] = []

        def calculate(_runner: object) -> FakeQueryResponse:
            tags = get_query_tags()
            observed_tags.append((tags.product, tags.feature))
            return FakeQueryResponse({"columns": [], "results": [], "hasMore": False, "limit": 1, "offset": 0})

        with patch("products.error_tracking.backend.presentation.views.query.EventsQueryRunner.calculate", calculate):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
                data={"issueId": self.issue_id},
                format="json",
            )

        assert response.status_code == 200
        assert observed_tags == [(Product.ERROR_TRACKING, Feature.QUERY)]

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_events_matches_by_fingerprint(self) -> None:
        self.create_issue()
        self.create_exception_event(
            issue_id="01936e80-45e5-70bd-baa1-bf2f2ca4c532",
            properties={"$session_id": "session-id-1"},
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["properties"]["$session_id"] == "session-id-1"

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_events_matches_events_without_issue_id(self) -> None:
        self.create_issue()
        self.create_exception_event(include_issue_id=False, properties={"$session_id": "session-id-1"})
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["properties"]["$session_id"] == "session-id-1"

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_events_without_fingerprints_returns_empty(self) -> None:
        ErrorTrackingIssue.objects.create(id=self.issue_id, team=self.team, name="TypeError")

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert response.status_code == 200
        assert response.json() == {"results": [], "hasMore": False, "limit": 1, "offset": 0}

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issue_events_returns_plural_exception_arrays_and_truncates_summary_text(self) -> None:
        long_text = "x" * 1200
        self.create_issue()
        self.create_exception_event(
            properties={
                "$session_id": "session-id-1",
                "$exception_values": [long_text],
                "$exception_list": [{"type": "TypeError", "value": long_text, "stacktrace": {"frames": []}}],
            }
        )
        flush_persons_and_events()

        summary_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )
        raw_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "verbosity": "raw",
            },
            format="json",
        )

        assert summary_response.status_code == 200
        assert raw_response.status_code == 200
        summary_event = summary_response.json()["results"][0]
        raw_event = raw_response.json()["results"][0]
        assert summary_event["properties"]["$exception_types"] == ["TypeError"]
        assert "[truncated from 1200 chars]" in summary_event["properties"]["$exception_values"][0]
        assert "[truncated from 1200 chars]" in summary_event["properties"]["$exception_list"][0]["value"]
        assert raw_event["properties"]["$exception_values"][0] == long_text
        assert raw_event["properties"]["$exception_list"][0]["value"] == long_text
        assert summary_event["properties"]["$session_id"] == "session-id-1"
