import importlib

from posthog.test.base import APIBaseTest

from django.apps import apps

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.signals.backend.models import SignalTeamConfig

MIGRATION = "products.signals.backend.migrations.0156_enable_pull_request_label"


class TestEnablePullRequestLabelMigration(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/config/"

    def _start_from_the_old_default(self) -> None:
        # update() rather than save(), so the starting point carries no audit entry of its own.
        SignalTeamConfig.objects.filter(team=self.team).update(pull_request_label_enabled=False)

    def _set_switch(self, enabled: bool) -> None:
        response = self.client.post(self._url(), data={"pull_request_label_enabled": enabled}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def _run_migration(self) -> None:
        importlib.import_module(MIGRATION).enable_pull_request_label(apps, None)

    def _enabled(self) -> bool:
        return SignalTeamConfig.objects.get(team=self.team).pull_request_label_enabled

    def test_a_team_that_never_touched_the_switch_gets_the_label(self):
        self._start_from_the_old_default()

        self._run_migration()

        assert self._enabled() is True

    def test_a_team_that_turned_the_label_off_keeps_it_off(self):
        # The switch shipped opt-in, so a team could turn it on and back off before the default
        # flipped. That `false` is a refusal, and the audit trail is the only record of it. Driving
        # the real endpoint is the point of this test: a hand-written ActivityLog row would prove
        # the filter matches itself, not that it matches what the settings page stores.
        self._start_from_the_old_default()
        self._set_switch(True)
        self._set_switch(False)

        self._run_migration()

        assert self._enabled() is False

    def test_a_team_that_changed_an_unrelated_setting_still_gets_the_label(self):
        # Guards the other side: matching the whole scope rather than this one field would read
        # any inbox settings edit as a refusal and leave those teams unlabelled.
        self._start_from_the_old_default()
        response = self.client.post(self._url(), data={"max_reports_per_day": 5}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert ActivityLog.objects.filter(team_id=self.team.pk, scope="SignalTeamConfig").exists()

        self._run_migration()

        assert self._enabled() is True
