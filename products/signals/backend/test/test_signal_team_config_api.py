from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration

from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig
from products.signals.backend.quota import SelfDrivingQuotaGate


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


class TestSelfDrivingStatusAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config = SignalTeamConfig.objects.get(team=self.team)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/config/self_driving_status/"

    @parameterized.expand(
        [
            ("never_set", None, True),
            ("explicitly_on", True, True),
            ("explicitly_off", False, False),
        ]
    )
    def test_autostart_enabled_reflects_effective_switch(self, _name, stored, expected):
        # Null must read as on: inverting that would tell every untouched team autostart is off.
        self.config.autostart_enabled = stored
        self.config.save(update_fields=["autostart_enabled"])
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_enabled"] is expected

    def test_github_connected_reflects_integration_presence(self):
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["github_connected"] is False
        assert data["quota_blocked"] is False

        Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.GITHUB, config={})
        response = self.client.get(self._url())
        assert response.json()["github_connected"] is True

    def test_quota_blocked_reflects_enforced_gate(self):
        with patch(
            "products.signals.backend.views.self_driving_quota_gate",
            return_value=SelfDrivingQuotaGate(limited=True, enforced=True),
        ):
            response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["quota_blocked"] is True

    @parameterized.expand(
        [
            ("no_source_rows", False, True, False),
            ("source_enabled_and_org_approved", True, True, True),
            ("source_enabled_without_ai_approval", True, None, False),
        ]
    )
    def test_error_tracking_signals_enabled_requires_source_and_consent(
        self, _name, create_source, ai_approved, expected
    ):
        # A team without an enabled error tracking source (or without AI approval) emits no
        # signals, so reporting enabled would point the nudge at the wrong setup step.
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        if create_source:
            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.ERROR_TRACKING,
                source_type=SignalSourceConfig.SourceType.ISSUE_CREATED,
                enabled=True,
            )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["error_tracking_signals_enabled"] is expected
