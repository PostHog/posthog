from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertThread, ErrorTrackingIssue
from products.error_tracking.backend.temporal.alerts.delivery import deliver_alert_notifications
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs


class TestAlertDelivery(BaseTest):
    def setUp(self):
        super().setUp()
        with team_scope(self.team.id):
            self.integration = Integration.objects.create(
                team=self.team,
                kind=Integration.IntegrationKind.SLACK.value,
                config={"team": {"id": "T123"}},
                sensitive_config={"access_token": "token"},
            )
            self.issue = ErrorTrackingIssue.objects.create(team=self.team)

    def _create_alert(self, *, triggers=None, enabled=True) -> ErrorTrackingAlert:
        with team_scope(self.team.id):
            return ErrorTrackingAlert.objects.create(
                team=self.team,
                name="Notify #alerts",
                enabled=enabled,
                triggers=triggers if triggers is not None else ["issue_created"],
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0123"},
            )

    def _inputs(self, event: str, notification_id: str = "notif-1", **overrides) -> AlertDeliveryWorkflowInputs:
        defaults = {
            "notification_id": notification_id,
            "team_id": self.team.id,
            "issue_id": str(self.issue.id),
            "event": event,
            "issue_name": "TypeError",
            "issue_description": "Something failed",
            "status": "Active",
            "actor_email": "dev@example.com",
        }
        defaults.update(overrides)
        return AlertDeliveryWorkflowInputs(**defaults)

    def _deliver(self, inputs: AlertDeliveryWorkflowInputs) -> tuple[int, MagicMock]:
        client = MagicMock()
        client.chat_postMessage.return_value = {"channel": "C0123", "ts": "111.222"}
        with patch("products.error_tracking.backend.temporal.alerts.delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = client
            delivered = deliver_alert_notifications(inputs)
        return delivered, client

    def _thread(self, alert: ErrorTrackingAlert) -> ErrorTrackingAlertThread | None:
        return ErrorTrackingAlertThread.objects.for_team(self.team.id).filter(alert=alert, issue=self.issue).first()

    def test_opener_posts_root_message_and_persists_thread(self):
        alert = self._create_alert(triggers=["issue_created"])

        delivered, client = self._deliver(self._inputs("$error_tracking_issue_created"))

        assert delivered == 1
        client.chat_postMessage.assert_called_once()
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C0123"
        assert "thread_ts" not in kwargs
        thread = self._thread(alert)
        assert thread is not None
        assert thread.external_ref == {"channel": "C0123", "ts": "111.222"}
        assert thread.delivered_event_uuids == ["notif-1"]

    def test_redelivered_notification_is_not_reposted(self):
        self._create_alert(triggers=["issue_created"])
        inputs = self._inputs("$error_tracking_issue_created")

        self._deliver(inputs)
        delivered, client = self._deliver(inputs)

        assert delivered == 0
        client.chat_postMessage.assert_not_called()

    def test_update_posts_reply_into_original_channel(self):
        alert = self._create_alert(triggers=["issue_created"])
        self._deliver(self._inputs("$error_tracking_issue_created"))
        # Repointing the alert must not move existing threads.
        alert.config = {"channel": "C_NEW"}
        alert.save()

        delivered, client = self._deliver(self._inputs("$error_tracking_issue_resolved", notification_id="notif-2"))

        assert delivered == 1
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C0123"
        assert kwargs["thread_ts"] == "111.222"
        assert "Resolved" in kwargs["text"]
        assert "dev@example.com" in kwargs["text"]
        thread = self._thread(alert)
        assert thread is not None
        assert thread.delivered_event_uuids == ["notif-1", "notif-2"]

    def test_update_without_thread_is_skipped(self):
        alert = self._create_alert(triggers=["issue_created"])

        delivered, client = self._deliver(self._inputs("$error_tracking_issue_resolved"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()
        assert self._thread(alert) is None

    def test_update_on_unrooted_thread_stays_unclaimed(self):
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            ErrorTrackingAlertThread.objects.create(team=self.team, alert=alert, issue=self.issue)

        delivered, client = self._deliver(self._inputs("$error_tracking_issue_resolved", notification_id="notif-3"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()
        thread = self._thread(alert)
        assert thread is not None
        # Unclaimed on purpose: once an opener posts the root, this update could
        # still deliver on a redelivery/retry.
        assert thread.delivered_event_uuids == []

    @parameterized.expand(
        [
            ("trigger_not_subscribed", {"triggers": ["issue_spiking"]}),
            ("alert_disabled", {"enabled": False}),
        ]
    )
    def test_non_matching_alert_does_not_open_thread(self, _name, alert_kwargs):
        alert = self._create_alert(**alert_kwargs)

        delivered, client = self._deliver(self._inputs("$error_tracking_issue_created"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()
        assert self._thread(alert) is None
