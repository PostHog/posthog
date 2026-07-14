from posthog.test.base import BaseTest

from posthog.models import Team

from products.error_tracking.backend.management.commands.backfill_error_tracking_autocapture_opt_in import Command
from products.error_tracking.backend.models import ErrorTrackingSettings


class TestBackfillErrorTrackingAutocaptureOptIn(BaseTest):
    def _run(self, *, live_run: bool = True) -> None:
        Command().handle(live_run=live_run, team_id=None, start_from_team_id=None, end_team_id=None)

    def _historical_opted_in_team(self) -> Team:
        # Simulate a team that opted in before the dual-write signal existed: True on Team, no settings
        # row. A queryset update bypasses the post_save signal that would otherwise create the row.
        team = Team.objects.create(organization=self.organization)
        Team.objects.filter(id=team.id).update(autocapture_exceptions_opt_in=True)
        return team

    def test_live_run_backfills_only_opted_in_teams(self):
        no_row = self._historical_opted_in_team()
        existing_row = self._historical_opted_in_team()
        ErrorTrackingSettings.objects.create(team=existing_row, project_rate_limit_value=42)
        not_opted_in = Team.objects.create(organization=self.organization, autocapture_exceptions_opt_in=False)
        never_set = Team.objects.create(organization=self.organization)

        self._run(live_run=True)

        assert ErrorTrackingSettings.objects.get(team=no_row).autocapture_exceptions_opt_in is True

        updated = ErrorTrackingSettings.objects.get(team=existing_row)
        assert updated.autocapture_exceptions_opt_in is True
        # A pre-existing settings row must keep its other fields.
        assert updated.project_rate_limit_value == 42

        assert not ErrorTrackingSettings.objects.filter(team=not_opted_in).exists()
        assert not ErrorTrackingSettings.objects.filter(team=never_set).exists()

    def test_dry_run_writes_nothing(self):
        team = self._historical_opted_in_team()

        self._run(live_run=False)

        assert not ErrorTrackingSettings.objects.filter(team=team).exists()
