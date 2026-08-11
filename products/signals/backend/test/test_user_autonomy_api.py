from posthog.test.base import APIBaseTest

from rest_framework import status

from products.signals.backend.models import AutonomyPriority, SignalUserAutonomyConfig


class TestUserAutonomyConfigAPI(APIBaseTest):
    def _url(self) -> str:
        return "/api/users/@me/signal_autonomy/"

    def test_get_returns_200_with_null_when_no_config_exists(self):
        assert not SignalUserAutonomyConfig.objects.filter(user=self.user).exists()
        response = self.client.get(self._url())
        # No saved config is the default state — it must read as an empty state (200 + null body),
        # not a 404 that pollutes the app's own request-failure telemetry on every inbox visit.
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() is None

    def test_get_returns_config_when_one_exists(self):
        SignalUserAutonomyConfig.objects.create(user=self.user, autostart_priority=AutonomyPriority.P2.value)
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_priority"] == AutonomyPriority.P2.value
