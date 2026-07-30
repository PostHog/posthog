from posthog.test.base import APIBaseTest

from rest_framework import status

from products.signals.backend.models import SignalUserAutonomyConfig


class TestSignalUserAutonomyAPI(APIBaseTest):
    def _url(self) -> str:
        return "/api/users/@me/signal_autonomy/"

    def test_get_returns_defaults_when_nothing_saved(self):
        assert not SignalUserAutonomyConfig.objects.filter(user=self.user).exists()
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["id"] is None
        assert data["autostart_priority"] is None
        assert data["slack_notification_channel"] is None
        # Reading defaults must not persist a row.
        assert not SignalUserAutonomyConfig.objects.filter(user=self.user).exists()

    def test_get_returns_saved_config(self):
        SignalUserAutonomyConfig.objects.create(user=self.user, autostart_priority="P2")
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["id"] is not None
        assert data["autostart_priority"] == "P2"
