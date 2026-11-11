from posthog.test.base import BaseTest

from posthog.models.integration import Integration

from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_config import sync_config_state


class TestSyncConfigState(BaseTest):
    def _integration(self, kind: str, sensitive_config: dict) -> Integration:
        return Integration.objects.create(team=self.team, kind=kind, sensitive_config=sensitive_config)

    def test_without_a_config_nothing_is_set_up(self) -> None:
        state = sync_config_state(self.team.id)

        assert state["app_integration_id"] is None
        assert state["has_webhook_secret"] is False
        assert state["has_track_credentials"] is False

    def test_reports_the_credentials_of_the_linked_integrations(self) -> None:
        app = self._integration("customerio-app", {"app_api_key": "key"})
        webhook = self._integration("customerio-webhook", {"webhook_signing_secret": "secret"})
        track = self._integration("customerio-track", {"site_id": "site", "api_key": "key"})
        OptOutSyncConfig.objects.create(
            team=self.team,
            app_integration=app,
            webhook_integration=webhook,
            webhook_enabled=True,
            track_integration=track,
            track_enabled=True,
        )

        state = sync_config_state(self.team.id)

        assert state["app_integration_id"] == app.id
        assert state["has_webhook_secret"] is True
        assert state["has_track_credentials"] is True

    def test_incomplete_credentials_do_not_count(self) -> None:
        OptOutSyncConfig.objects.create(
            team=self.team,
            webhook_integration=self._integration("customerio-webhook", {}),
            track_integration=self._integration("customerio-track", {"site_id": "site"}),
        )

        state = sync_config_state(self.team.id)

        assert state["has_webhook_secret"] is False
        assert state["has_track_credentials"] is False
