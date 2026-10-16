import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.funnel_step import FunnelStepRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

NOW = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)
DROP_HOUR = datetime(2026, 1, 15, 9, tzinfo=UTC)
PATHNAMES = ["/login", "/home", "/billing"]
PAGES = [f"app.example.com{pathname}" for pathname in PATHNAMES]


class TestFunnelStepLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def _visit(self, hour: datetime, index: int, pages: int, issue: ErrorTrackingIssue | None = None) -> None:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"impact-funnel-{hour.isoformat()}-{index}"))
        opened = hour + timedelta(minutes=index % 59)
        events: list[tuple[str, datetime, dict[str, Any]]] = [
            ("$pageview", opened + timedelta(seconds=30 * page), {"$pathname": PATHNAMES[page]})
            for page in range(pages)
        ]
        if issue:
            # The error fires as the home page loads.
            events.append(
                (
                    "$exception",
                    opened + timedelta(seconds=32),
                    {
                        "$pathname": "/home",
                        "$exception_fingerprint": f"fp::{issue.id}",
                        "$exception_types": ["TypeError"],
                        "$exception_values": ["Cannot read properties of undefined (reading 'plan')"],
                    },
                )
            )
        for event, timestamp, extra in events:
            _create_event(
                distinct_id=session_id,
                event=event,
                team=self.team,
                properties={"$session_id": session_id, "$host": "app.example.com", "$lib": "web", **extra},
                timestamp=timestamp.isoformat(),
            )

    def _hour(self, hour: datetime, visits: int, reached_home: int, reached_billing: int) -> None:
        for i in range(visits):
            self._visit(hour, i, 3 if i < reached_billing else 2 if i < reached_home else 1)

    def _drop(self, hour: datetime, issue: ErrorTrackingIssue | None = None) -> None:
        # Visits reach home as usual, but only 10 of 150 go on to billing, and most of the others get the error.
        for i in range(250):
            pages = 3 if i < 10 else 2 if i < 150 else 1
            self._visit(hour, i, pages, issue=issue if 25 <= i < 150 else None)

    @parameterized.expand([("stable_chain", []), ("chain_that_drops_every_few_days", [2, 5, 8])])
    @time_machine.travel(NOW, tick=False)
    def test_names_the_broken_step_and_the_error_on_its_first_page(self, _name: str, earlier_drop_days: list[int]):
        issue = self._create_issue("BillingPlanMissing")
        # Usually 36 of 60 visits reach home and 18 of those go on to billing.
        for days in range(1, 16):
            if days in earlier_drop_days:
                self._drop(DROP_HOUR - timedelta(days=days))
            else:
                self._hour(DROP_HOUR - timedelta(days=days), 60, 36, 18)
        # Earlier today, so the pages people move between are discovered from the last day.
        self._hour(DROP_HOUR - timedelta(hours=4), 150, 90, 45)
        self._drop(DROP_HOUR, issue)
        flush_persons_and_events()

        meta = FunnelStepRecommendation().compute(self.team)

        self.assertTrue(meta["evaluable"])
        self.assertEqual(meta["chains"], [PAGES])
        if earlier_drop_days:
            self.assertEqual(
                (meta["incidents"], meta["muted"], meta["issues"]), ([], [{"pages": PAGES, "incidents": 4}], [])
            )
            return
        incident = meta["incidents"][0]
        self.assertEqual(
            (incident["hour"], incident["starts"], incident["finishes"], incident["usual_rate"]),
            (DROP_HOUR.isoformat(), 250, 10, 0.3),
        )
        self.assertEqual(
            [(step["entered"], step["continued"], step["usual_rate"]) for step in incident["steps"]],
            [(250, 150, 0.6), (150, 10, 0.5)],
        )
        self.assertEqual((incident["broken_step"], incident["clear"]), (1, True))
        self.assertEqual(
            [(i["name"], i["from_path"], i["to_path"], i["exposed"], i["exposed_finished"]) for i in meta["issues"]],
            [("BillingPlanMissing", PAGES[1], PAGES[2], 125, 0)],
        )
