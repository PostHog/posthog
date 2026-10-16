from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.suppressed_events import SuppressedEventsRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

# A real error carries a stack in the app's own code, which is what makes it something to act on.
CONNECT_BUG = {
    "$exception_types": ["TypeError"],
    "$exception_values": ["Cannot read properties of undefined (reading 'token')"],
    "$exception_list": [
        {
            "type": "TypeError",
            "value": "Cannot read properties of undefined (reading 'token')",
            "stacktrace": {
                "type": "resolved",
                "frames": [{"source": "https://app.example.com/static/app.js", "in_app": True, "resolved": True}],
            },
        }
    ],
}


# A failed request with no stack in the app's code is noise, even when the same visits stop connecting.
FAILED_REQUEST = {
    "$exception_types": ["TypeError"],
    "$exception_values": ["Failed to fetch"],
    "$exception_list": [{"type": "TypeError", "value": "Failed to fetch", "stacktrace": {"type": "raw", "frames": []}}],
}


class TestSuppressedEventsLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    @parameterized.expand([("code_bug", CONNECT_BUG, ["BrokenConnect"]), ("noise", FAILED_REQUEST, [])])
    def test_flags_event_people_stop_sending_after_the_error(
        self, _name: str, error: dict[str, Any], flagged_names: list[str]
    ):
        issue = self._create_issue("BrokenConnect")
        start = timezone.now() - timedelta(hours=3)
        page = {"$lib": "web", "$host": "app.example.com", "$pathname": "/connect"}
        # 200 visits without the error, 120 of which connect an integration. None of the 60 visits with it do.
        for i in range(260):
            session_id = str(uuid7())
            with_error = i >= 200
            opened = start + timedelta(seconds=30 * i)
            events: list[tuple[str, datetime, dict[str, Any]]] = [("$pageview", opened, {})]
            if with_error:
                exception = {"$exception_fingerprint": f"fp::{issue.id}", **error}
                events.append(("$exception", opened + timedelta(seconds=2), exception))
            elif i % 5 < 3:
                events.append(("integration_connected", opened + timedelta(minutes=1), {}))
            for event, timestamp, extra in events:
                _create_event(
                    distinct_id=session_id,
                    event=event,
                    team=self.team,
                    properties={**page, "$session_id": session_id, **extra},
                    timestamp=timestamp.isoformat(),
                )
        flush_persons_and_events()

        meta = SuppressedEventsRecommendation().compute(self.team)

        # When the only issue to test is noise, the lens still ran and found nothing, rather than being unable to run.
        self.assertTrue(meta["evaluable"])
        self.assertEqual([i["name"] for i in meta["issues"]], flagged_names)
        if not flagged_names:
            return
        flagged = meta["issues"][0]
        self.assertEqual(
            (flagged["path"], flagged["sessions"], flagged["comparison_sessions"], flagged["events"]),
            (
                "app.example.com/connect",
                60,
                200,
                [{"event": "integration_connected", "issue_share": 0.0, "comparison_share": 0.6}],
            ),
        )
