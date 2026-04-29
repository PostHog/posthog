from __future__ import annotations

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from products.error_tracking.backend.api.query_utils import build_event_where
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2


def test_issue_event_search_escapes_like_wildcards_and_quotes() -> None:
    where = build_event_where("issue-id", r"a%_'\\")[1]

    assert r"\%" in where
    assert r"\_" in where
    assert r"\'" in where
    assert r"\\" in where


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

    def create_issue(self, issue_id: str | None = None, fingerprint: str | None = None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(id=issue_id or self.issue_id, team=self.team, name="TypeError")
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=issue, fingerprint=fingerprint or self.fingerprint
        )
        return issue

    def create_exception_event(
        self,
        *,
        issue_id: str | None = None,
        fingerprint: str | None = None,
        properties: dict[str, object] | None = None,
    ) -> None:
        resolved_issue_id = issue_id or self.issue_id
        resolved_fingerprint = fingerprint or self.fingerprint
        _create_event(
            distinct_id="user-1",
            event="$exception",
            team=self.team,
            properties={
                "$exception_issue_id": resolved_issue_id,
                "$exception_fingerprint": resolved_fingerprint,
                "$exception_types": ["TypeError"],
                "$exception_values": ["Cannot read properties of undefined"],
                **(properties or {}),
            },
            timestamp=now() - relativedelta(hours=1),
        )

    @freeze_time("2026-04-24T12:00:00Z")
    def test_issues_list_accepts_typed_filters_and_matches_release_precisely(self) -> None:
        self.create_issue()
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
