import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models import Team
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.flow_drop import FlowDropRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

NOW = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)
DROP_HOUR = datetime(2026, 1, 15, 9, tzinfo=UTC)
CODE_BUG = ("TypeError", "Cannot read properties of undefined (reading 'token')")


class TestFlowDropLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, team: Team, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.pk)
        return issue

    def _login(
        self,
        team: Team,
        hour: datetime,
        index: int,
        finished: bool,
        issue: ErrorTrackingIssue | None = None,
        error: tuple[str, str] = CODE_BUG,
    ) -> None:
        # The same login number gives the same session in every team, so a join that crossed teams would mix them up.
        session_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"impact-login-{hour.isoformat()}-{index}"))
        opened = hour + timedelta(minutes=index % 59)
        page = {"$session_id": session_id, "$host": "app.example.com", "$lib": "web"}
        events: list[tuple[str, datetime, dict[str, Any]]] = [("$pageview", opened, {"$pathname": "/login"})]
        if finished:
            events.append(("$pageview", opened + timedelta(seconds=30), {"$pathname": "/home"}))
        if issue:
            exc_type, value = error
            events.append(
                (
                    "$exception",
                    opened + timedelta(seconds=2),
                    {
                        "$pathname": "/login",
                        "$exception_fingerprint": f"fp::{issue.id}",
                        "$exception_types": [exc_type],
                        "$exception_values": [value],
                    },
                )
            )
        for event, timestamp, extra in events:
            _create_event(
                distinct_id=session_id,
                event=event,
                team=team,
                properties={**page, **extra},
                timestamp=timestamp.isoformat(),
            )

    def _usual_logins(self, team: Team) -> None:
        # 4 previous days where 55 of 100 logins reach the home page, at the hour of the drop.
        for days in range(1, 5):
            for i in range(100):
                self._login(team, DROP_HOUR - timedelta(days=days), i, finished=i < 55)
        # Earlier today, so the flow is discovered from the last 24 hours.
        for i in range(60):
            self._login(team, DROP_HOUR - timedelta(hours=4), i, finished=i < 33)

    def _drop(self, team: Team, issue: ErrorTrackingIssue, exposed: range, error: tuple[str, str] = CODE_BUG) -> None:
        # 30 of 250 logins get through, and the issue fires as the page loads in the given failed visits.
        for i in range(250):
            self._login(team, DROP_HOUR, i, finished=i < 30, issue=issue if i in exposed else None, error=error)

    @parameterized.expand(
        [
            ("code_bug", CODE_BUG, [("BrokenLogin", 120, 0)]),
            # A harmless pattern can sit in failed visits without breaking them, so it is not attached.
            ("harmless_pattern", ("Error", "ResizeObserver loop completed with undelivered notifications."), []),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_attaches_the_issue_that_sat_in_the_failed_visits(
        self, _name: str, error: tuple[str, str], expected: list[tuple[str, int, int]]
    ):
        issue = self._create_issue(self.team, "BrokenLogin")
        bystander = self._create_issue(self.team, "Bystander")
        self._usual_logins(self.team)
        self._drop(self.team, issue, range(30, 150), error)
        # Another issue fires in visits that finish as often as the rest.
        for i in [0, 1, 2, *range(150, 175)]:
            self._login(self.team, DROP_HOUR + timedelta(minutes=1), 1000 + i, finished=i < 3, issue=bystander)
        flush_persons_and_events()

        meta = FlowDropRecommendation().compute(self.team)

        self.assertTrue(meta["evaluable"])
        self.assertEqual(meta["flows"], [{"from_path": "app.example.com/login", "to_path": "app.example.com/home"}])
        self.assertEqual(meta["surges"], [])
        incident = meta["incidents"][0]
        self.assertEqual(
            (
                incident["hour"],
                incident["starts"],
                incident["finishes"],
                incident["usual_starts"],
                incident["usual_finishes"],
                incident["usual_rate"],
            ),
            (DROP_HOUR.isoformat(), 278, 33, 100, 55, 0.55),
        )
        self.assertEqual([(i["name"], i["exposed"], i["exposed_finished"]) for i in meta["issues"]], expected)

    @time_machine.travel(NOW, tick=False)
    def test_reports_extra_traffic_with_usual_logins_as_a_surge_not_a_break(self):
        self._usual_logins(self.team)
        # Four times the usual logins reach the page in the drop hour, and the usual 55 get through.
        for i in range(400):
            self._login(self.team, DROP_HOUR, i, finished=i < 55)
        flush_persons_and_events()

        meta = FlowDropRecommendation().compute(self.team)

        self.assertEqual(meta["incidents"], [])
        self.assertEqual(
            [(s["hour"], s["starts"], s["finishes"]) for s in meta["surges"]], [(DROP_HOUR.isoformat(), 400, 55)]
        )

    @time_machine.travel(NOW, tick=False)
    def test_a_batch_of_teams_gives_each_team_its_own_result(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._usual_logins(self.team)
        self._usual_logins(other_team)
        self._drop(self.team, self._create_issue(self.team, "BrokenLogin"), range(30, 150))
        self._drop(other_team, self._create_issue(other_team, "OtherBroken"), range(130, 250))
        flush_persons_and_events()

        lens = FlowDropRecommendation()
        batch = lens.compute_batch([self.team.pk, other_team.pk])

        self.assertEqual([i["name"] for i in batch[self.team.pk]["issues"]], ["BrokenLogin"])
        self.assertEqual(batch, {self.team.pk: lens.compute(self.team), other_team.pk: lens.compute(other_team)})
