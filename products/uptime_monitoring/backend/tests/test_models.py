import pytest
from posthog.test.base import BaseTest

from posthog.models import Team
from posthog.models.scoping.manager import TeamScopeError

from products.uptime_monitoring.backend.models import UptimeMonitor


class TestUptimeMonitorScoping(BaseTest):
    def test_reads_are_team_scoped_and_fail_closed(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        own = UptimeMonitor.objects.unscoped().create(team=self.team, name="Own", url="https://example.com")
        UptimeMonitor.objects.unscoped().create(team=other_team, name="Other", url="https://example.org")

        assert list(UptimeMonitor.objects.for_team(self.team.id)) == [own]
        with pytest.raises(TeamScopeError):
            list(UptimeMonitor.objects.all())
