from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.model_activity import ActingUserContext

from products.signals.backend.facade.api import set_default_slack_notification_channel
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
        assert data["default_autostart_priority"] == "P4"
        # Null until a team explicitly opts out; the guard treats null as autostart-on.
        assert data["autostart_enabled"] is None

    def test_get_config_lazily_creates_when_no_config_exists(self):
        self.config.delete()
        assert not SignalTeamConfig.objects.filter(team=self.team).exists()
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_autostart_priority"] == "P4"
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

    @parameterized.expand(
        [
            ("disable", True, False),
            ("enable", False, True),
        ]
    )
    def test_update_autostart_enabled(self, _name, initial, sent):
        self.config.autostart_enabled = initial
        self.config.save(update_fields=["autostart_enabled"])
        response = self.client.post(self._url(), data={"autostart_enabled": sent}, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_enabled"] is sent
        self.config.refresh_from_db()
        assert self.config.autostart_enabled is sent

    def test_partial_update_preserves_autostart_enabled(self):
        # A team that turned autostart off must not have it silently re-enabled when it later
        # edits an unrelated field.
        self.config.autostart_enabled = False
        self.config.save(update_fields=["autostart_enabled"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.autostart_enabled is False

    def _activity(self) -> list[ActivityLog]:
        return list(ActivityLog.objects.filter(team_id=self.team.id, scope="SignalTeamConfig"))

    def test_auto_created_config_is_not_activity_logged(self):
        # Every team gets a row with default settings it never chose, so logging its creation
        # would put a spurious entry in every new project's activity log.
        assert self._activity() == []

    def test_threshold_change_is_activity_logged_with_who_and_what(self):
        response = self.client.post(self._url(), data={"default_autostart_priority": "P1"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()

        entries = self._activity()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.activity == "updated"
        assert entry.user == self.user
        assert entry.detail is not None
        assert entry.detail["changes"] == [
            {
                "type": "SignalTeamConfig",
                "action": "changed",
                "field": "default_autostart_priority",
                "before": "P4",
                "after": "P1",
            }
        ]

    def test_resending_current_values_is_not_activity_logged(self):
        response = self.client.post(
            self._url(),
            data={"default_autostart_priority": self.config.default_autostart_priority},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._activity() == []

    def test_slack_onboarding_channel_is_activity_logged_for_a_team_with_no_config_row(self):
        # Teams that predate SignalTeamConfig have no row until something writes one, so Slack
        # onboarding can be the first writer. Creating the row with the channel already in it would
        # make the team's first real settings change land as "created", which is dropped as
        # auto-provisioning.
        self.config.delete()

        set_default_slack_notification_channel(self.team.id, "C123|#posthog-inbox")

        entries = self._activity()
        assert len(entries) == 1
        assert entries[0].detail is not None
        assert entries[0].detail["changes"] == [
            {
                "type": "SignalTeamConfig",
                "action": "created",
                "field": "default_slack_notification_channel",
                "before": None,
                "after": "C123|#posthog-inbox",
            }
        ]

    def test_slack_channel_change_is_attributed_to_the_acting_user(self):
        # The Slack interactivity handlers resolve the clicker and wrap the channel write in
        # ActingUserContext, so the entry names who clicked rather than reading as system activity.
        with ActingUserContext(self.user):
            set_default_slack_notification_channel(self.team.id, "C123|#posthog-inbox")

        entries = self._activity()
        assert len(entries) == 1
        assert entries[0].user == self.user
