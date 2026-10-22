from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.uptime_monitoring.backend.models import UptimeMonitor


@patch("products.uptime_monitoring.backend.facade.api.is_uptime_monitoring_enabled", return_value=True)
class TestUptimeMonitorAPI(APIBaseTest):
    def _url(self, monitor_id: object = None) -> str:
        base = f"/api/projects/{self.team.id}/uptime_monitors/"
        return f"{base}{monitor_id}/" if monitor_id else base

    def test_create_update_list_delete(self, _flag: MagicMock) -> None:
        created = self.client.post(self._url(), {"name": "Site", "url": "https://example.com"}, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        monitor_id = created.json()["id"]
        assert UptimeMonitor.objects.for_team(self.team.id).get(id=monitor_id).created_by_id == self.user.id

        updated = self.client.patch(self._url(monitor_id), {"enabled": False, "interval_seconds": 600}, format="json")
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["enabled"] is False
        assert updated.json()["interval_seconds"] == 600
        assert updated.json()["name"] == "Site"

        listed = self.client.get(self._url())
        assert [m["id"] for m in listed.json()["results"]] == [monitor_id]

        assert self.client.delete(self._url(monitor_id)).status_code == status.HTTP_204_NO_CONTENT
        assert not UptimeMonitor.objects.for_team(self.team.id).exists()

    def test_invalid_body_is_rejected(self, _flag: MagicMock) -> None:
        response = self.client.post(self._url(), {"name": "Site", "url": "not a url"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("get",), ("patch",), ("delete",)])
    def test_another_teams_monitor_is_not_found(self, _flag: MagicMock, method: str) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other = UptimeMonitor.objects.for_team(other_team.id).create(
            team=other_team, name="Other", url="https://example.org"
        )
        response = getattr(self.client, method)(self._url(other.id), {"name": "Taken"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other.refresh_from_db()
        assert other.name == "Other"

    def test_flag_off_hides_the_api(self, flag: MagicMock) -> None:
        flag.return_value = False
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND
