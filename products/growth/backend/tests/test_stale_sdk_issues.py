import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Organization, Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.rollups.freshness import RollupWindow

from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.stale_sdk_issues import find_stale_sdk_issues, resolve_sdk_issues_for_teams
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck

WINDOW = RollupWindow(start=dt.date(2026, 10, 22), end=dt.date(2026, 10, 28))


class TestStaleSdkIssues(BaseTest):
    def _issue(self, team: Team) -> HealthIssue:
        payload = {"sdk_name": "web"}
        return HealthIssue.objects.create(
            team=team,
            kind=SdkOutdatedCheck.kind,
            severity=HealthIssue.Severity.WARNING,
            payload=payload,
            unique_hash=HealthIssue.compute_unique_hash(SdkOutdatedCheck.kind, payload, ["sdk_name"]),
        )

    def _traffic(self, team: Team) -> None:
        SdkVersionsDaily.objects.unscoped().create(
            team_id=team.id,
            day=WINDOW.end,
            lib="web",
            lib_version="1.0.0",
            event_count=10,
            max_timestamp=dt.datetime(2026, 10, 28, tzinfo=dt.UTC),
        )

    def test_resolves_only_teams_the_check_can_no_longer_reach(self) -> None:
        self.user.last_login = timezone.now()
        self.user.save()
        reachable = self.team
        silent = Team.objects.create(organization=self.organization)
        abandoned = Team.objects.create(organization=Organization.objects.create(name="No logins"))
        for team in (reachable, silent, abandoned):
            self._issue(team)
        self._traffic(reachable)
        self._traffic(abandoned)

        stale = find_stale_sdk_issues(WINDOW)
        resolved = resolve_sdk_issues_for_teams(stale.team_ids)

        assert stale.team_ids == sorted([silent.id, abandoned.id])
        assert resolved == 2
        active = HealthIssue.objects.filter(kind=SdkOutdatedCheck.kind, status=HealthIssue.Status.ACTIVE)
        assert list(active.values_list("team_id", flat=True)) == [reachable.id]
