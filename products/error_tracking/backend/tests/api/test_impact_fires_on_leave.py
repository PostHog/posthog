from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models import Team
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.fires_on_leave import FiresOnLeaveRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

# A whole hour, so the lens's window, which ends on the last whole hour, holds every session below.
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)


class TestFiresOnLeaveLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, team: Team, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.pk)
        return issue

    def _seed(self, team: Team, issue: ErrorTrackingIssue | None) -> None:
        start = NOW - timedelta(hours=3)
        # Fixed session ids keep the hashed baseline sample stable: 37 of these 160 land in it. Every team gets the
        # same ids, so grouping that ignored the team would merge their sessions.
        for i in range(160):
            session_id = f"0191a0b2-7c3d-7000-8000-{i:012x}"
            fires_on_leave = issue is not None and i < 45
            opened = start + timedelta(minutes=i)
            leave_after = 60.3 if fires_on_leave else 120
            events = [
                ("$pageview", opened, {}),
                ("$autocapture", opened + timedelta(seconds=5), {"$event_type": "click"}),
                ("$pageleave", opened + timedelta(seconds=leave_after), {}),
            ]
            if fires_on_leave and issue is not None:
                events.append(
                    ("$exception", opened + timedelta(seconds=60), {"$exception_fingerprint": f"fp::{issue.id}"})
                )
            for event, timestamp, extra in events:
                _create_event(
                    distinct_id=session_id,
                    event=event,
                    team=team,
                    properties={"$lib": "web", "$session_id": session_id, **extra},
                    timestamp=timestamp.isoformat(),
                )

    @time_machine.travel(NOW, tick=False)
    def test_flags_issue_that_fires_as_the_page_unloads(self):
        self._seed(self.team, self._create_issue(self.team, "LeavingError"))
        flush_persons_and_events()

        meta = FiresOnLeaveRecommendation().compute(self.team)

        self.assertTrue(meta["evaluable"])
        self.assertEqual([i["name"] for i in meta["issues"]], ["LeavingError"])
        flagged = meta["issues"][0]
        self.assertEqual(
            (flagged["sessions"], flagged["leave_share"], flagged["background_share"], meta["baseline_leave_share"]),
            (45, 1.0, 1.0, 0.0),
        )

    @time_machine.travel(NOW, tick=False)
    def test_a_batch_of_teams_gives_each_team_its_own_result(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._seed(self.team, self._create_issue(self.team, "LeavingError"))
        self._seed(other_team, None)
        flush_persons_and_events()

        lens = FiresOnLeaveRecommendation()
        batch = lens.compute_batch([self.team.pk, other_team.pk])

        self.assertEqual([i["name"] for i in batch[self.team.pk]["issues"]], ["LeavingError"])
        self.assertEqual(batch, {self.team.pk: lens.compute(self.team), other_team.pk: lens.compute(other_team)})
