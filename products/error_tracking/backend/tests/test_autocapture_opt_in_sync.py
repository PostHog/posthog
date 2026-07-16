from posthog.test.base import BaseTest

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingSettings


class TestAutocaptureOptInSync(BaseTest):
    def _settings(self, team: Team) -> ErrorTrackingSettings | None:
        return ErrorTrackingSettings.objects.filter(team=team).first()

    def test_opting_in_mirrors_to_settings_row(self):
        team = Team.objects.create(organization=self.organization, autocapture_exceptions_opt_in=True)

        settings = self._settings(team)
        assert settings is not None
        assert settings.autocapture_exceptions_opt_in is True

    def test_opting_out_syncs_existing_row_without_deleting_it(self):
        team = Team.objects.create(organization=self.organization, autocapture_exceptions_opt_in=True)
        ErrorTrackingSettings.objects.filter(team=team).update(project_rate_limit_value=42)

        team.autocapture_exceptions_opt_in = False
        team.save()

        settings = self._settings(team)
        assert settings is not None
        assert settings.autocapture_exceptions_opt_in is False
        # Other settings on the row must survive a disable.
        assert settings.project_rate_limit_value == 42

    def test_never_opting_in_creates_no_row(self):
        team = Team.objects.create(organization=self.organization, autocapture_exceptions_opt_in=False)

        assert self._settings(team) is None

    def test_save_not_touching_the_field_does_not_recreate_row(self):
        team = Team.objects.create(organization=self.organization, autocapture_exceptions_opt_in=True)
        ErrorTrackingSettings.objects.filter(team=team).delete()

        team.name = "renamed"
        team.save(update_fields=["name"])

        assert self._settings(team) is None
