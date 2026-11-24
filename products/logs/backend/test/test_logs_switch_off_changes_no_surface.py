from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.core.management import call_command

from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.test.platform_handover import hand_over_team

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _switch_off(team_id: int) -> None:
    call_command("switch_off_legacy_logs_alert_rows", "--team-id", str(team_id), "--apply", stdout=None)


def _alert(team: Any) -> LogsAlertConfiguration:
    return LogsAlertConfiguration.objects.create(
        team=team, name="API errors", filters={"serviceNames": ["api"]}, threshold_count=5
    )


class TestSwitchOffChangesNoLogsSurface(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.traveller = time_machine.travel(NOW, tick=False)
        self.traveller.start()
        self.addCleanup(self.traveller.stop)
        self.alert = _alert(self.team)
        hand_over_team(self.team.id, NOW - timedelta(days=10))
        self.url = f"/api/projects/{self.team.id}/logs/alerts/"

    def _get(self, path: str) -> Any:
        response = self.client.get(path)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _surfaces(self) -> dict[str, Any]:
        return {
            "api list": self._get(self.url)["results"],
            "api retrieve": self._get(f"{self.url}{self.alert.id}/"),
            "api events": self._get(f"{self.url}{self.alert.id}/events/"),
        }

    def test_switching_off_the_rows_changes_no_surface(self) -> None:
        before = self._surfaces()

        _switch_off(self.team.id)

        assert not LogsAlertConfiguration.objects.filter(team_id=self.team.id, enabled=True).exists()
        after = self._surfaces()
        assert {name: after[name] for name in before if after[name] != before[name]} == {}

    def test_a_switched_off_alert_still_edits_as_on(self) -> None:
        _switch_off(self.team.id)

        response = self.client.patch(f"{self.url}{self.alert.id}/", {"name": "renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        with team_scope(self.team.id):
            copy = get_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.LOGS.value],
                configuration_id=platform_testing.copy_of(self.alert.id).id,
            )
        assert (response.json()["enabled"], copy.enabled if copy else None) == (True, True)
