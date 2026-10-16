import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models import Team
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.lost_visitor import LostVisitorRecommendation
from products.error_tracking.backend.logic.recommendations.quick_leave import QuickLeaveRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
# The two days the lenses read: the day that ended a day ago, and the same day a week earlier.
DAY_STARTS = (NOW - timedelta(days=2), NOW - timedelta(days=9))
IN_APP_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Instagram 300.0"
CODE_BUG = ("TypeError", "Cannot read properties of undefined (reading 'plan')")
FAILED_REQUEST = ("TypeError", "Failed to fetch")


def _stack(exc_type: str, value: str, frames: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "$exception_types": [exc_type],
        "$exception_values": [value],
        "$exception_list": [{"type": exc_type, "value": value, "stacktrace": {"type": "resolved", "frames": frames}}],
    }


# A frame in the app's own bundle. A stack that reaches the app's code is what makes an error something to act on.
APP_FRAME = {"source": "https://app.example.com/static/app.js", "in_app": True, "resolved": True}


def _person(day: int, index: int) -> uuid.UUID:
    # The same visitor numbers give the same person in every team, so a lookup that crossed teams would mix them up.
    return uuid.uuid5(uuid.NAMESPACE_OID, f"impact-visitor-{day}-{index}")


class TestPageLoadLenses(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, team: Team, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.pk)
        return issue

    def _visit(
        self,
        team: Team,
        person_id: uuid.UUID,
        opened: datetime,
        stay_seconds: int,
        *,
        comes_back: bool,
        issue: ErrorTrackingIssue | None,
        error_after_seconds: float = 1,
        agent: str = "",
        error: tuple[str, str] = CODE_BUG,
    ) -> None:
        session_id = str(uuid7())
        page = {"$lib": "web", "$host": "app.example.com", "$pathname": "/billing", "$raw_user_agent": agent}
        events: list[tuple[str, datetime, str, dict[str, Any]]] = [
            ("$pageview", opened, session_id, {}),
            ("$pageleave", opened + timedelta(seconds=stay_seconds), session_id, {}),
        ]
        if issue:
            events.append(
                (
                    "$exception",
                    opened + timedelta(seconds=error_after_seconds),
                    session_id,
                    {"$exception_fingerprint": f"fp::{issue.id}", **_stack(*error, [APP_FRAME])},
                )
            )
        if comes_back:
            events.append(("$pageview", opened + timedelta(hours=23), str(uuid7()), {}))
        for event, timestamp, session, extra in events:
            _create_event(
                distinct_id=str(person_id),
                person_id=person_id,
                event=event,
                team=team,
                properties={**page, "$session_id": session, "$window_id": session, **extra},
                timestamp=timestamp.isoformat(),
            )

    def _seed(
        self,
        team: Team,
        broken: ErrorTrackingIssue,
        *,
        everyone_comes_back: bool = False,
        in_app_only: ErrorTrackingIssue | None = None,
        unload: ErrorTrackingIssue | None = None,
        failed_request: ErrorTrackingIssue | None = None,
    ) -> None:
        for day, day_start in enumerate(DAY_STARTS):
            opened = day_start + timedelta(hours=2)
            visitors = iter(range(1000))
            # Without errors, 30 of 150 regular visits leave within 10 seconds, and every other visitor comes back.
            for i in range(150):
                self._visit(
                    team,
                    _person(day, next(visitors)),
                    opened,
                    5 if i >= 120 else 60,
                    comes_back=everyone_comes_back or i % 2 == 0,
                    issue=None,
                )
            # Every visit with the error leaves within 10 seconds.
            for _ in range(60):
                self._visit(team, _person(day, next(visitors)), opened, 5, comes_back=everyone_comes_back, issue=broken)
            if failed_request:
                # A failed request goes with the same quick exits, but it is noise nobody can act on in the page.
                for _ in range(60):
                    self._visit(
                        team,
                        _person(day, next(visitors)),
                        opened,
                        5,
                        comes_back=everyone_comes_back,
                        issue=failed_request,
                        error=FAILED_REQUEST,
                    )
            if in_app_only:
                # In-app browsers leave quickly and do not come back, with or without their error.
                for i in range(40):
                    self._visit(
                        team,
                        _person(day, next(visitors)),
                        opened,
                        5 if i >= 4 else 60,
                        comes_back=False,
                        issue=None,
                        agent=IN_APP_AGENT,
                    )
                for i in range(60):
                    self._visit(
                        team,
                        _person(day, next(visitors)),
                        opened,
                        5 if i >= 6 else 60,
                        comes_back=False,
                        issue=in_app_only,
                        agent=IN_APP_AGENT,
                    )
            if unload:
                # This error fires as people close the page, half a second before they leave.
                for _ in range(60):
                    self._visit(
                        team,
                        _person(day, next(visitors)),
                        opened,
                        3,
                        comes_back=False,
                        issue=unload,
                        error_after_seconds=2.5,
                    )

    @time_machine.travel(NOW, tick=False)
    def test_flags_page_load_errors_against_visitors_of_the_same_kind_on_both_days(self):
        broken = self._create_issue(self.team, "BrokenBilling")
        in_app_only = self._create_issue(self.team, "InAppOnly")
        unload = self._create_issue(self.team, "FiresOnClose")
        failed_request = self._create_issue(self.team, "FailedRequest")
        self._seed(self.team, broken, in_app_only=in_app_only, unload=unload, failed_request=failed_request)
        flush_persons_and_events()

        quick_leave = QuickLeaveRecommendation().compute(self.team)
        lost_visitor = LostVisitorRecommendation().compute(self.team)

        # The comparison rates are smoothed by half a pageview each way: 30.5 of 151 quick leaves, 75.5 of 151 lost.
        self.assertEqual(
            [
                (i["name"], i["rate"], i["expected_rate"], i["returned_rate"], i["expected_returned_rate"])
                for i in quick_leave["issues"]
            ],
            [("BrokenBilling", 1.0, 0.202, 0.0, 0.5)],
        )
        self.assertEqual(
            [(i["name"], i["rate"], i["expected_rate"]) for i in lost_visitor["issues"]],
            [("BrokenBilling", 1.0, 0.5)],
        )

    @time_machine.travel(NOW, tick=False)
    def test_a_batch_of_teams_gives_each_team_its_own_result(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._seed(self.team, self._create_issue(self.team, "BrokenBilling"))
        # The same visitors in the other team all come back, so a return lookup across teams would hide every loss.
        self._seed(other_team, self._create_issue(other_team, "OtherBroken"), everyone_comes_back=True)
        flush_persons_and_events()

        quick_leave, lost_visitor = QuickLeaveRecommendation(), LostVisitorRecommendation()
        lost_batch = lost_visitor.compute_batch([self.team.pk, other_team.pk])

        self.assertEqual([i["name"] for i in lost_batch[self.team.pk]["issues"]], ["BrokenBilling"])
        self.assertEqual(
            lost_batch, {self.team.pk: lost_visitor.compute(self.team), other_team.pk: lost_visitor.compute(other_team)}
        )
        self.assertEqual(
            quick_leave.compute_batch([self.team.pk, other_team.pk]),
            {self.team.pk: quick_leave.compute(self.team), other_team.pk: quick_leave.compute(other_team)},
        )
