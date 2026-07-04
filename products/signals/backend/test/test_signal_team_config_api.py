from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.signals.backend.models import SignalTeamConfig


class TestSignalTeamConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A SignalTeamConfig is auto-created for every team via register_team_extension_signal.
        self.config = SignalTeamConfig.objects.get(team=self.team)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/config/"

    def test_get_config_includes_default_slack_notification_channel(self):
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] is None
        assert data["default_autostart_priority"] == "P3"

    def test_get_config_lazily_creates_when_no_config_exists(self):
        self.config.delete()
        assert not SignalTeamConfig.objects.filter(team=self.team).exists()
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_autostart_priority"] == "P3"
        assert data["default_slack_notification_channel"] is None
        assert SignalTeamConfig.objects.filter(team=self.team).exists()

    def test_post_config_lazily_creates_when_no_config_exists(self):
        self.config.delete()
        assert not SignalTeamConfig.objects.filter(team=self.team).exists()
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] == "C123|#posthog-signals"
        config = SignalTeamConfig.objects.get(team=self.team)
        assert config.default_slack_notification_channel == "C123|#posthog-signals"

    @parameterized.expand(
        [
            ("set", None, "C123|#posthog-signals", "C123|#posthog-signals"),
            ("clear", "C123|#posthog-signals", None, None),
        ]
    )
    def test_update_default_slack_notification_channel(self, _name, initial, sent, expected):
        if initial is not None:
            self.config.default_slack_notification_channel = initial
            self.config.save(update_fields=["default_slack_notification_channel"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": sent},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] == expected
        self.config.refresh_from_db()
        assert self.config.default_slack_notification_channel == expected

    def test_partial_update_preserves_default_autostart_priority(self):
        self.config.default_autostart_priority = "P2"
        self.config.save(update_fields=["default_autostart_priority"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.default_autostart_priority == "P2"
        assert self.config.default_slack_notification_channel == "C123|#posthog-signals"

    def test_get_config_includes_autostart_base_branches(self):
        self.config.autostart_base_branches = {"acme/web": "staging"}
        self.config.save(update_fields=["autostart_base_branches"])
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_base_branches"] == {"acme/web": "staging"}

    def test_update_autostart_base_branches_normalizes_and_persists(self):
        response = self.client.post(
            self._url(),
            # Mixed case key is lowercased; blank-branch entry is dropped.
            data={"autostart_base_branches": {"Acme/Web": "  staging  ", "acme/api": ""}},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_base_branches"] == {"acme/web": "staging"}
        self.config.refresh_from_db()
        assert self.config.autostart_base_branches == {"acme/web": "staging"}

    def test_update_autostart_base_branches_rejects_malformed_repo_key(self):
        response = self.client.post(
            self._url(),
            data={"autostart_base_branches": {"not-a-repo": "staging"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "autostart_base_branches"

    def test_partial_update_preserves_autostart_base_branches(self):
        self.config.autostart_base_branches = {"acme/web": "staging"}
        self.config.save(update_fields=["autostart_base_branches"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.autostart_base_branches == {"acme/web": "staging"}
