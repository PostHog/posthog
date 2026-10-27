from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.conf import settings
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.error_tracking.backend.facade.contracts import ErrorTrackingIssueSummary, IssueSummaryCategory
from products.error_tracking.backend.facade.query_utils import (
    ISSUE_BREAKDOWN_TOP_VALUES,
    MAX_STACK_FRAMES,
    BreakdownRange,
    breakdown_query_date_range,
    build_issue_event_where,
    build_issue_filters,
    build_search_query,
    build_sparkline,
    build_trend,
    dedupe_repeated_stacktraces,
    map_issue_breakdown,
    normalize_stacktrace,
    resolve_breakdown_range,
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
    where = build_issue_event_where("01936e7f-d7ff-7314-b2d4-7627981e34f0", r"a%_'\\")

    assert where[0] == "issue_id = toUUID('01936e7f-d7ff-7314-b2d4-7627981e34f0')"
    assert r"\%" in where[1]
    assert r"\_" in where[1]
    assert r"\'" in where[1]
    assert r"\\" in where[1]


def test_search_query_preserves_quotes() -> None:
    assert build_search_query({"searchQuery": "can't read property"}) == "can't read property"
    assert build_search_query({"searchQuery": '"cannot read"', "filePath": "src/app.ts"}) == '"cannot read" src/app.ts'


def test_release_filter_adds_substring_prefilter() -> None:
    filters = build_issue_filters({"release": "2026.04.24"})

    assert filters[0] == {
        "type": "hogql",
        "key": "position(toString(properties.$exception_release), '2026.04.24') > 0",
    }
    assert "properties.$exception_release.version" in str(filters[1]["key"])


@parameterized.expand(
    [
        ("float values", [1.0, 2.5], 2, [1.0, 2.5]),
        ("doubled odd resolution adds pairs back together", [1, 0, 2, 3, 0, 1], 3, [1, 5, 1]),
    ]
)
def test_build_sparkline(_name: str, volume_range: list[float], volume_resolution: int, expected: list[float]) -> None:
    assert build_sparkline({"aggregations": {"volumeRange": volume_range}}, volume_resolution) == expected


OLD_FIRST_SEEN = datetime(2026, 4, 1, tzinfo=UTC)


@parameterized.expand(
    [
        ("increasing", [2, 2, 5, 5], OLD_FIRST_SEEN, {"direction": "increasing", "change_percent": 150}),
        ("decreasing", [5, 5, 2, 2], OLD_FIRST_SEEN, {"direction": "decreasing", "change_percent": -60}),
        ("small change is stable", [4, 4, 5, 4], OLD_FIRST_SEEN, {"direction": "stable"}),
        (
            "20% drop is stable",
            [3, 2, 2, 2],
            OLD_FIRST_SEEN,
            {"direction": "stable", "change_percent": -20},
        ),
        (
            "25% drop is decreasing",
            [2, 2, 1, 2],
            OLD_FIRST_SEEN,
            {"direction": "decreasing", "change_percent": -25},
        ),
        ("first seen in the current half", [0, 0, 1, 3], datetime(2026, 4, 23, 6, tzinfo=UTC), {"direction": "new"}),
        ("quiet before the current half", [0, 0, 1, 3], OLD_FIRST_SEEN, {"direction": "increasing"}),
        ("odd bucket count leaves the middle out", [1, 9, 1], OLD_FIRST_SEEN, {"direction": "stable"}),
    ]
)
def test_build_trend(_name: str, values: list[int], first_seen: datetime, expected: dict[str, object]) -> None:
    start = datetime(2026, 4, 21, tzinfo=UTC)
    buckets = [
        {"label": (start + timedelta(days=index)).isoformat(), "value": value} for index, value in enumerate(values)
    ]
    trend = build_trend({"aggregations": {"volume_buckets": buckets}}, first_seen)
    assert trend is not None
    assert {key: trend.get(key) for key in expected} == expected


def test_normalize_stacktrace_keeps_the_frames_closest_to_the_error() -> None:
    frames = [{"mangled_name": f"frame_{index}", "in_app": True} for index in range(MAX_STACK_FRAMES + 20)]

    stacktrace = normalize_stacktrace({"frames": frames}, only_app_frames=True)

    assert stacktrace is not None
    kept = cast(list[dict[str, object]], stacktrace["frames"])
    assert len(kept) == MAX_STACK_FRAMES
    assert kept[0]["mangled_name"] == "frame_20"
    assert kept[-1]["mangled_name"] == f"frame_{MAX_STACK_FRAMES + 19}"
    assert stacktrace["frames_omitted"] == 20


def test_normalize_stacktrace_does_not_mark_a_short_stack() -> None:
    stacktrace = normalize_stacktrace({"frames": [{"mangled_name": "main", "in_app": True}]}, only_app_frames=True)

    assert stacktrace is not None
    assert "frames_omitted" not in stacktrace


def test_dedupe_repeated_stacktraces_references_the_first_copy_of_the_stack() -> None:
    def exception(line: int) -> dict[str, object]:
        frame = {"mangled_name": "submitOrder", "line": line, "in_app": True}
        return {"type": "TypeError", "stacktrace": {"frames": [frame]}}

    def event(uuid: str, *lines: int) -> dict[str, object]:
        return {"uuid": uuid, "properties": {"$exception_list": [exception(line) for line in lines]}}

    events = dedupe_repeated_stacktraces(
        [
            # Two exceptions with different stacks, then an exception that repeats the first stack in the same event.
            event("event-1", 42, 43, 42),
            event("event-2", 43),
            event("event-3", 44),
        ]
    )

    stacks = [[exception["stacktrace"] for exception in cast(Any, e["properties"])["$exception_list"]] for e in events]
    assert stacks[0][0]["frames"][0]["line"] == 42
    assert stacks[0][1]["frames"][0]["line"] == 43
    assert stacks[0][2] == {"same_as_event": "event-1", "same_as_exception": 0}
    assert stacks[1][0] == {"same_as_event": "event-1", "same_as_exception": 1}
    assert stacks[2][0]["frames"][0]["line"] == 44


BREAKDOWN_NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


@parameterized.expand(
    [
        ("short_relative_range", {"date_from": "-7d"}, BREAKDOWN_NOW - timedelta(days=7), BREAKDOWN_NOW, False),
        ("long_relative_range", {"date_from": "-90d"}, BREAKDOWN_NOW - timedelta(days=30), BREAKDOWN_NOW, True),
        ("unbounded_range", {"date_from": "all"}, BREAKDOWN_NOW - timedelta(days=30), BREAKDOWN_NOW, True),
        (
            "long_explicit_range",
            {"date_from": "2026-01-01T00:00:00Z", "date_to": "2026-03-01T00:00:00Z"},
            datetime(2026, 1, 30, tzinfo=UTC),
            datetime(2026, 3, 1, tzinfo=UTC),
            True,
        ),
    ]
)
def test_resolve_breakdown_range_limits_the_range_to_30_days(
    _name: str,
    date_range: dict[str, object],
    expected_from: datetime,
    expected_to: datetime,
    expected_limited: bool,
) -> None:
    assert resolve_breakdown_range(date_range, ZoneInfo("UTC"), BREAKDOWN_NOW) == BreakdownRange(
        date_from=expected_from, date_to=expected_to, range_limited=expected_limited
    )


def test_map_issue_breakdown_drops_empty_values_and_dimensions() -> None:
    long_path = "/" + "a" * 500
    null_label = "$$_posthog_breakdown_null_$$"
    results: dict[str, object] = {
        "$pathname": {
            "values": [{"value": long_path, "count": 3}, {"value": null_label, "count": 1}],
            "total_count": 4,
        },
        "$current_url": {"values": [{"value": "https://example.test/a", "count": 3}], "total_count": 4},
        "$browser": {"values": [{"value": "Chrome", "count": 4}], "total_count": 4},
        "$os": {"values": [{"value": null_label, "count": 4}], "total_count": 4},
        "$session_id": {
            "values": [{"value": null_label, "count": 2}, {"value": "session-1", "count": 2}],
            "total_count": 4,
        },
    }

    breakdown = map_issue_breakdown(results)

    assert breakdown["occurrences"] == 4
    assert breakdown["sample_session_ids"] == ["session-1"]
    top_values = cast(dict[str, Any], breakdown["top_values"])
    # The URL is left out when the events have a path, and a dimension with only missing values is left out.
    assert set(top_values) == {"path", "browser"}
    assert top_values["browser"] == [{"value": "Chrome", "count": 4}]
    assert len(top_values["path"]) == 1
    assert top_values["path"][0]["count"] == 3
    assert len(top_values["path"][0]["value"]) == 200


def test_map_issue_breakdown_returns_urls_when_events_have_no_path() -> None:
    results: dict[str, object] = {
        "$pathname": {"values": [{"value": "", "count": 2}], "total_count": 2},
        "$current_url": {"values": [{"value": "https://api.example.test/orders", "count": 2}], "total_count": 2},
    }

    top_values = cast(dict[str, Any], map_issue_breakdown(results)["top_values"])

    assert top_values == {"url": [{"value": "https://api.example.test/orders", "count": 2}]}


@parameterized.expand(
    [
        ("relative_range_keeps_the_request", {"date_from": "-7d"}, {"date_from": "-7d", "date_to": None}, False),
        (
            "long_range_is_limited",
            {"date_from": "-90d"},
            {"date_from": (BREAKDOWN_NOW - timedelta(days=30)).isoformat(), "date_to": None},
            True,
        ),
        (
            "relative_date_to_is_resolved",
            {"date_from": "-7d", "date_to": "-1d"},
            {"date_from": "-7d", "date_to": (BREAKDOWN_NOW - timedelta(days=1)).isoformat()},
            False,
        ),
    ]
)
def test_breakdown_query_date_range(
    _name: str, date_range: dict[str, object], expected: dict[str, object], expected_limited: bool
) -> None:
    assert breakdown_query_date_range(date_range, ZoneInfo("UTC"), BREAKDOWN_NOW) == (expected, expected_limited)


SUMMARIES_FACADE = "products.error_tracking.backend.facade.summaries"
STORED_SUMMARY = ErrorTrackingIssueSummary(
    issue_id=UUID("01936e7f-d7ff-7314-b2d4-7627981e34f0"),
    what_happened="Checkout throws a TypeError when the cart is empty.",
    likely_cause="The cart total reads a property of an undefined line item.",
    who_is_affected="Users who open checkout with an empty cart.",
    suggested_next_step="Guard the line item lookup in the cart total.",
    category=IssueSummaryCategory.OWN_CODE,
    model="test-model",
    generated_at=datetime(2026, 4, 24, 11, 0, tzinfo=UTC),
    checked_at=datetime(2026, 4, 24, 11, 0, tzinfo=UTC),
)
STORED_SUMMARY_PAYLOAD = {
    "what_happened": STORED_SUMMARY.what_happened,
    "likely_cause": STORED_SUMMARY.likely_cause,
    "who_is_affected": STORED_SUMMARY.who_is_affected,
    "suggested_next_step": STORED_SUMMARY.suggested_next_step,
    "category": "own_code",
    "generated_at": "2026-04-24T11:00:00+00:00",
}


class TestErrorTrackingQueryAPI(ClickhouseTestMixin, APIBaseTest):
    issue_id = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
    fingerprint = "issue-fingerprint"

    def setUp(self) -> None:
        super().setUp()
        _create_person(team=self.team, distinct_ids=["user-1"], is_identified=True)
        flush_persons_and_events()

    def create_issue(
        self,
        issue_id: str | None = None,
        fingerprint: str | None = None,
        severity: str | None = None,
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=issue_id or self.issue_id, team=self.team, name="TypeError", severity=severity
        )
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
        timestamp: datetime | None = None,
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
            timestamp=timestamp or now() - relativedelta(hours=1),
        )

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issues_list_accepts_typed_filters_and_matches_release_precisely(self) -> None:
        self.create_issue()
        self.create_exception_event(
            properties={
                "$lib": "posthog-js",
                "$browser": "Chrome",
                "$current_url": "https://example.test/checkout",
                "$exception_release": {
                    "id": "release-id-1",
                    "version": "2026.04.24",
                    "project": "posthog-js",
                    "timestamp": "2026-04-24T10:00:00Z",
                    "metadata": {"git": {"commit_id": "commit-123", "branch": "main"}},
                },
            }
        )
        flush_persons_and_events()

        with patch(f"{SUMMARIES_FACADE}.start_issue_summary_generation") as start_generation:
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issues",
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
        assert "summary" not in response.json()["results"][0]
        start_generation.assert_not_called()

        project_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={
                "status": "all",
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "release": "posthog-js",
            },
            format="json",
        )

        assert project_response.status_code == 200
        assert project_response.json()["results"] == []

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_queries_return_severity(self) -> None:
        self.create_issue(severity=ErrorTrackingIssue.Severity.HIGH)
        self.create_exception_event()
        flush_persons_and_events()

        list_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={"status": "all", "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )
        detail_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert list_response.status_code == 200
        assert list_response.json()["results"][0]["severity"] == "high"
        assert detail_response.status_code == 200
        assert detail_response.json()["severity"] == "high"

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

    @parameterized.expand([("too_large", 201), ("time_unit", "day")])
    def test_rejects_invalid_volume_resolution_with_accepted_values(self, _name: str, value: object) -> None:
        list_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issues",
            data={"volumeResolution": value},
            format="json",
        )
        detail_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "volumeResolution": value},
            format="json",
        )

        for response in (list_response, detail_response):
            assert response.status_code == 400
            assert "integer bucket count from 0 to 200" in response.content.decode()

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issues_list_filters_by_assignee(self) -> None:
        self.create_issue()
        self.create_exception_event()
        ErrorTrackingIssueAssignment.objects.create(issue_id=self.issue_id, user=self.user, team=self.team)
        # re-sync with a strictly newer version so the assignment wins argMax over the create-time row
        with time_machine.travel(now() + timedelta(seconds=1), tick=False):
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

    @parameterized.expand(
        [
            ("counts_only", {"volumeResolution": 0}, 1, False),
            ("with_volume", {"volumeResolution": 1}, 1, True),
        ]
    )
    def test_issues_list_returns_compact_rows(
        self, _name: str, data: dict[str, object], expected_resolution: int, expect_volume: bool
    ) -> None:
        observed_queries: list[tuple[int, int | None]] = []

        def calculate(runner: ErrorTrackingQueryRunner) -> FakeQueryResponse:
            observed_queries.append((runner.query.volumeResolution, runner.query.limit))
            issue = {
                "id": self.issue_id,
                "name": "TypeError",
                "description": "x" * 2000,
                "status": "active",
                "aggregations": {
                    "occurrences": 3,
                    "users": 2,
                    "sessions": 1,
                    "volumeRange": [3],
                    "volume_buckets": [{"label": "2026-04-17T12:00:00+00:00", "value": 3}],
                },
            }
            return FakeQueryResponse({"results": [issue], "hasMore": False, "limit": 10, "offset": 0})

        with patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate", calculate):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issues",
                data=data,
                format="json",
            )

        assert response.status_code == 200
        assert observed_queries == [(expected_resolution, 10)]
        row = response.json()["results"][0]
        assert len(row["description"]) == 300
        assert row["description"].endswith("[truncated from 2000 chars]")
        assert row["aggregations"]["occurrences"] == 3
        assert ("volumeRange" in row["aggregations"]) is expect_volume
        assert ("volume_buckets" in row["aggregations"]) is expect_volume

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
        assert observed_tags == [(Product.ERROR_TRACKING, Feature.QUERY)] * 3

    def test_issue_detail_does_not_expand_fingerprints(self) -> None:
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
        assert observed_volume_resolutions == [2]
        assert observed_filter_groups == [None]

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

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_returns_impact_top_frame_and_releases(self) -> None:
        # In the current trend half, so only the merged fingerprint keeps trend from reading new.
        first_seen = datetime(2026, 4, 24, 6, tzinfo=UTC)
        merged_first_seen = datetime(2026, 4, 1, 8, tzinfo=UTC)
        issue = ErrorTrackingIssue.objects.create(id=self.issue_id, team=self.team, name="TypeError")
        for fingerprint, fingerprint_first_seen in [
            (self.fingerprint, first_seen),
            ("merged-fingerprint", merged_first_seen),
        ]:
            created = ErrorTrackingIssueFingerprintV2.objects.create(
                team=self.team, issue=issue, fingerprint=fingerprint
            )
            # The model sets first_seen on create, so overwrite it the way cymbal writes it: the first event's timestamp.
            ErrorTrackingIssueFingerprintV2.objects.filter(id=created.id).update(first_seen=fingerprint_first_seen)
        # Sync once: under the frozen clock a second sync gets the same ReplacingMergeTree version.
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        # A fingerprint merged in from an older issue, with no events in the date range.
        source_issue_id = "01936e7f-d7ff-7314-b2d4-7627981e34f1"
        self.create_exception_event(
            issue_id=source_issue_id,
            fingerprint="merged-fingerprint",
            timestamp=merged_first_seen,
            properties={"$exception_release": {"id": "release-id-1", "version": "2026.04.01"}},
        )
        # Arrived after the fingerprint was created, but happened first.
        self.create_exception_event(
            issue_id=source_issue_id,
            fingerprint="merged-fingerprint",
            timestamp=merged_first_seen - timedelta(hours=2),
            properties={
                "$exception_release": {
                    "id": "release-id-0",
                    "version": "2026.03.31",
                    "project": "posthog-js",
                    "timestamp": "2026-03-31T09:00:00Z",
                }
            },
        )
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
                "$exception_release": {
                    "id": "release-id-1",
                    "version": "2026.04.24",
                    "project": "posthog-js",
                    "timestamp": "2026-04-24T10:00:00Z",
                    "metadata": {"git": {"commit_id": "commit-123", "branch": "main"}},
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
        assert data["first_seen"] == "2026-04-24T06:00:00Z"
        assert data["trend"] == {
            "direction": "increasing",
            "current_occurrences": 1,
            "previous_occurrences": 0,
            "previous_from": "2026-04-23T00:00:00+00:00",
            "previous_to": "2026-04-24T00:00:00+00:00",
            "current_from": "2026-04-24T00:00:00+00:00",
        }
        assert data["first_release"] == {
            "version": "2026.03.31",
            "project": "posthog-js",
            "timestamp": "2026-03-31T09:00:00Z",
        }

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_trend_splits_an_odd_volume_resolution_at_the_midpoint(self) -> None:
        self.create_issue()
        for timestamp in [
            "2026-04-21T12:00:00Z",
            "2026-04-22T06:00:00Z",
            "2026-04-22T18:00:00Z",
            "2026-04-23T12:00:00Z",
        ]:
            self.create_exception_event(timestamp=datetime.fromisoformat(timestamp))
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "2026-04-21T00:00:00Z", "date_to": "2026-04-24T00:00:00Z"},
                "includeSparkline": True,
                "volumeResolution": 3,
            },
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sparkline"] == [1, 2, 1]
        assert data["trend"]["previous_occurrences"] == 2
        assert data["trend"]["current_occurrences"] == 2
        assert data["trend"]["current_from"] == "2026-04-22T12:00:00+00:00"

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
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

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_distinguishes_missing_issue_from_empty_date_range(self) -> None:
        self.create_issue(severity=ErrorTrackingIssue.Severity.HIGH)

        empty_range_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "2026-04-23T00:00:00Z", "date_to": "2026-04-23T01:00:00Z"},
            },
            format="json",
        )
        missing_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )

        assert empty_range_response.status_code == 200
        assert empty_range_response.json()["impact"] == {}
        assert empty_range_response.json()["severity"] == "high"
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

    @parameterized.expand(
        [
            (
                "issue",
                True,
                {"includeSparkline": True},
                {"include_breakdown": False, "include_sparkline": True, "summary_status": "unavailable"},
            ),
            (
                "issue",
                False,
                {"includeSparkline": True},
                {"include_breakdown": False, "include_sparkline": True, "summary_status": "unavailable"},
            ),
            ("issue_events", True, {}, {}),
        ]
    )
    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_reads_capture_an_event_for_existing_issues_only(
        self,
        endpoint: str,
        has_exceptions: bool,
        extra_body: dict[str, object],
        expected_properties: dict[str, object],
    ) -> None:
        self.create_issue()
        if has_exceptions:
            self.create_exception_event()
            flush_persons_and_events()
        token = self.create_personal_api_key_with_scopes(["error_tracking:read"])

        with patch("posthog.event_usage.posthoganalytics.capture") as mock_capture:
            found = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/{endpoint}",
                data={"issueId": self.issue_id, **extra_body},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
            missing = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/{endpoint}",
                data={"issueId": "00000000-0000-0000-0000-000000000000", **extra_body},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        assert found.status_code == 200
        assert missing.status_code == 404
        read_events = [
            call.kwargs["properties"]
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "error_tracking_issue_read"
        ]
        assert read_events == [
            {
                **read_events[0],
                "issue_id": self.issue_id,
                "endpoint": endpoint,
                "access_method": "personal_api_key",
                **expected_properties,
            }
        ]
        if endpoint == "issue":
            assert isinstance(read_events[0]["facts_ms"], int)
            assert isinstance(read_events[0]["summary_wait_ms"], int)

    @parameterized.expand(
        [
            ("stored", STORED_SUMMARY, True, None, None, False, "ready", STORED_SUMMARY_PAYLOAD),
            (
                "stored_without_category",
                replace(STORED_SUMMARY, category=None),
                False,
                None,
                None,
                False,
                "ready",
                {key: value for key, value in STORED_SUMMARY_PAYLOAD.items() if key != "category"},
            ),
            ("generated_within_the_wait", None, True, STORED_SUMMARY, None, True, "ready", STORED_SUMMARY_PAYLOAD),
            ("wait_times_out", None, True, None, None, True, "generating", None),
            ("gates_off", None, False, None, None, False, "unavailable", None),
            (
                "saved_before_the_start",
                [None, STORED_SUMMARY],
                False,
                None,
                None,
                False,
                "ready",
                STORED_SUMMARY_PAYLOAD,
            ),
            ("facade_fails", None, None, None, RuntimeError("broker down"), False, "unavailable", None),
        ]
    )
    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_returns_the_summary(
        self,
        _name: str,
        stored: ErrorTrackingIssueSummary | None | list[ErrorTrackingIssueSummary | None],
        started: bool | None,
        waited: ErrorTrackingIssueSummary | None,
        start_error: Exception | None,
        expect_wait: bool,
        expected_status: str,
        expected_summary: dict[str, object] | None,
    ) -> None:
        self.create_issue()
        self.create_exception_event()
        flush_persons_and_events()
        clock = [100.0]

        def wait(*_args: object, **_kwargs: object) -> ErrorTrackingIssueSummary | None:
            clock[0] += 2.5
            return waited

        with (
            patch("products.error_tracking.backend.presentation.views.query.time") as view_time,
            patch(
                f"{SUMMARIES_FACADE}.get_issue_summary",
                side_effect=stored if isinstance(stored, list) else lambda *_args, **_kwargs: stored,
            ),
            patch(
                f"{SUMMARIES_FACADE}.start_issue_summary_generation", return_value=started, side_effect=start_error
            ) as start_generation,
            patch(f"{SUMMARIES_FACADE}.wait_for_issue_summary", side_effect=wait) as wait_for_summary,
            patch("posthog.event_usage.posthoganalytics.capture") as mock_capture,
        ):
            view_time.monotonic.side_effect = lambda: clock[0]
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["summary_status"] == expected_status
        assert response.json().get("summary") == expected_summary
        assert response.json()["impact"]["occurrences"] == 1
        start_generation.assert_called_once_with(self.team.id, self.issue_id, user=self.user)
        assert wait_for_summary.called == expect_wait
        [read_event] = [
            call.kwargs["properties"]
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "error_tracking_issue_read"
        ]
        assert (read_event["facts_ms"], read_event["summary_wait_ms"]) == (0, 2500 if expect_wait else 0)

    def test_issue_read_succeeds_when_capture_fails(self) -> None:
        self.create_issue()

        with patch("posthog.event_usage.posthoganalytics.capture", side_effect=RuntimeError("capture down")):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/query/issue",
                data={"issueId": self.issue_id},
                format="json",
            )

        assert response.status_code == 200

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

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
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

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
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

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_events_without_fingerprints_returns_empty(self) -> None:
        ErrorTrackingIssue.objects.create(id=self.issue_id, team=self.team, name="TypeError")

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"}},
            format="json",
        )

        assert response.status_code == 200
        assert response.json() == {"results": [], "hasMore": False, "limit": 1, "offset": 0}

    def test_issue_events_honors_user_property_access(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        property_definition = PropertyDefinition.objects.create(
            team=self.team,
            name="$referrer",
            type=PropertyDefinition.Type.EVENT,
        )
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                property_definition_id=str(property_definition.id),
                access_level=PropertyAccessLevel.NONE,
                organization_member_id=self.organization_membership.id,
            ),
        )
        self.create_issue()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={"issueId": self.issue_id, "include": ["navigation"]},
            format="json",
        )

        assert response.status_code == 400
        assert "Access to property '$referrer' is restricted" in str(response.json())

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_omits_breakdown_by_default(self) -> None:
        self.create_issue()
        self.create_exception_event(properties={"$current_url": "https://example.test/checkout"})
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id},
            format="json",
        )

        assert response.status_code == 200
        assert "breakdown" not in response.json()

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_breakdown_aggregates_matching_events(self) -> None:
        self.create_issue()
        for pathname, session_id, lib in [
            ("/checkout", "session-id-1", "web"),
            ("/checkout", "session-id-1", "web"),
            ("/cart", "session-id-2", "web"),
            ("/cart", "", "posthog-python"),
            ("/cart", "", "posthog-python"),
        ]:
            self.create_exception_event(
                properties={
                    "$pathname": pathname,
                    "$current_url": f"https://example.test{pathname}",
                    "$session_id": session_id,
                    "$browser": "Chrome",
                    "$lib": lib,
                }
            )
        self.create_exception_event(
            issue_id="01936e7f-d7ff-7314-b2d4-7627981e34f1",
            fingerprint="other-fingerprint",
            properties={"$current_url": "https://example.test/other"},
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "includeBreakdown": True},
            format="json",
        )

        assert response.status_code == 200
        breakdown = response.json()["breakdown"]
        assert breakdown["occurrences"] == 5
        assert breakdown["range_limited"] is False
        # Sessions with the most events first; events without a session are not a session.
        assert breakdown["sample_session_ids"] == ["session-id-1", "session-id-2"]
        top_values = breakdown["top_values"]
        assert top_values["path"] == [{"value": "/cart", "count": 3}, {"value": "/checkout", "count": 2}]
        assert top_values["browser"] == [{"value": "Chrome", "count": 5}]
        assert top_values["library"] == [{"value": "web", "count": 3}, {"value": "posthog-python", "count": 2}]
        # The URL repeats the path here, and no event has an OS or a screen name.
        assert set(top_values) == {"path", "browser", "library"}

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_breakdown_keeps_empty_values_out_of_top_values(self) -> None:
        self.create_issue()
        for index in range(ISSUE_BREAKDOWN_TOP_VALUES):
            self.create_exception_event(properties={"$pathname": f"/page-{index}"})
        # More events have an empty or no path than have any single real path, so a missing value would take a
        # slot if the query ranked it and the response kept it.
        for _ in range(ISSUE_BREAKDOWN_TOP_VALUES):
            self.create_exception_event(properties={"$pathname": ""})
            self.create_exception_event()
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "includeBreakdown": True},
            format="json",
        )

        assert response.status_code == 200
        paths = [item["value"] for item in response.json()["breakdown"]["top_values"]["path"]]
        assert sorted(paths) == sorted(f"/page-{index}" for index in range(ISSUE_BREAKDOWN_TOP_VALUES))

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_detail_breakdown_masks_restricted_properties(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="$pathname", type=PropertyDefinition.Type.EVENT
        )
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                property_definition_id=str(property_definition.id),
                access_level=PropertyAccessLevel.NONE,
                organization_member_id=self.organization_membership.id,
            ),
        )
        self.create_issue()
        self.create_exception_event(properties={"$pathname": "/checkout", "$browser": "Chrome"})
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue",
            data={"issueId": self.issue_id, "includeBreakdown": True},
            format="json",
        )

        assert response.status_code == 200
        top_values = response.json()["breakdown"]["top_values"]
        assert "path" not in top_values
        assert "/checkout" not in str(response.json())
        assert top_values["browser"] == [{"value": "Chrome", "count": 1}]

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
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
        assert summary_response.status_code == 200
        summary_event = summary_response.json()["results"][0]
        assert summary_event["properties"]["$exception_types"] == ["TypeError"]
        assert "[truncated from 1200 chars]" in summary_event["properties"]["$exception_values"][0]
        assert "[truncated from 1200 chars]" in summary_event["properties"]["$exception_list"][0]["value"]
        assert summary_event["properties"]["$session_id"] == "session-id-1"

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_events_returns_a_repeated_stack_trace_once(self) -> None:
        self.create_issue()
        exception_list = [
            {
                "type": "TypeError",
                "value": "Cannot read properties of undefined",
                "stacktrace": {"frames": [{"mangled_name": "submitOrder", "line": 42, "in_app": True}]},
            }
        ]
        for _ in range(2):
            self.create_exception_event(properties={"$exception_list": exception_list})
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "include": ["stacktrace"],
                "limit": 2,
            },
            format="json",
        )

        assert response.status_code == 200
        first, second = response.json()["results"]
        assert first["properties"]["$exception_list"][0]["stacktrace"]["frames"][0]["line"] == 42
        assert second["properties"]["$exception_list"][0]["stacktrace"] == {
            "same_as_event": first["uuid"],
            "same_as_exception": 0,
        }

    @time_machine.travel("2026-04-24T12:00:00Z", tick=False)
    def test_issue_events_returns_only_requested_context_groups(self) -> None:
        self.create_issue()
        self.create_exception_event(
            properties={
                "$lib": "posthog-js",
                "$current_url": "https://example.test/checkout",
                "$exception_level": "error",
                "$exception_handled": False,
                "$exception_release": {"id": "release-id", "version": "2026.04.24"},
                "$cymbal_errors": ["source map unavailable"],
                "$trace_id": "00000000000000000000000000000123",
                "$span_id": "0000000000000456",
                "$ai_trace_id": "ai-trace-id",
                "$ai_span_id": "ai-span-id",
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read properties of undefined",
                        "stacktrace": {
                            "frames": [
                                {
                                    "mangled_name": "submitOrder",
                                    "source": "src/checkout.ts",
                                    "line": 42,
                                    "in_app": True,
                                    "code_variables": {"order": {"customer": None, "total": 42}},
                                }
                            ]
                        },
                    }
                ],
            }
        )
        flush_persons_and_events()

        stack_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "include": ["stacktrace"],
            },
            format="json",
        )
        variables_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/query/issue_events",
            data={
                "issueId": self.issue_id,
                "dateRange": {"date_from": "-1d", "date_to": "2026-04-25T00:00:00Z"},
                "include": ["exception", "code_variables", "release", "correlation", "diagnostics"],
            },
            format="json",
        )

        assert stack_response.status_code == 200
        assert variables_response.status_code == 200
        stack_properties = stack_response.json()["results"][0]["properties"]
        variables_properties = variables_response.json()["results"][0]["properties"]
        stack_frame = stack_properties["$exception_list"][0]["stacktrace"]["frames"][0]
        variables_frame = variables_properties["$exception_list"][0]["stacktrace"]["frames"][0]
        assert "code_variables" not in stack_frame
        # The native-JSON table does not store a null leaf, so the null variable is absent there.
        expected_variables = (
            {"order": {"total": 42}}
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
            else {"order": {"customer": None, "total": 42}}
        )
        assert variables_frame["code_variables"] == expected_variables
        assert variables_properties["$exception_level"] == "error"
        assert variables_properties["$exception_handled"] is False
        assert variables_properties["$exception_release"] == {"id": "release-id", "version": "2026.04.24"}
        assert variables_properties["$cymbal_errors"] == ["source map unavailable"]
        assert variables_properties["$trace_id"] == "00000000000000000000000000000123"
        assert variables_properties["$span_id"] == "0000000000000456"
        assert variables_properties["$ai_trace_id"] == "ai-trace-id"
        assert variables_properties["$ai_span_id"] == "ai-span-id"
        assert "$exception_issue_id" not in variables_properties
        assert "$lib" not in variables_properties
        assert "$current_url" not in variables_properties

    # The runner's access check reads the token owner's RBAC, not the token's granted scopes, so a
    # kind registered on the generic query endpoint without a _QUERY_KIND_SCOPES entry is reachable
    # by any token holding only query:read.
    @parameterized.expand(
        [
            (["query:read"], 403),
            (["error_tracking:read"], 403),
            (["query:read", "error_tracking:read"], 200),
        ]
    )
    def test_releases_query_needs_both_scopes(self, scopes: list[str], expected_status: int) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": {"kind": "ErrorTrackingReleasesQuery", "issueId": self.issue_id}},
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()
