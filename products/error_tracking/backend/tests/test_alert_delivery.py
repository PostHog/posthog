from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertThread, ErrorTrackingIssue
from products.error_tracking.backend.temporal.alerts.delivery import plan_alert_deliveries
from products.error_tracking.backend.temporal.alerts.dispatch import start_alert_delivery_workflow
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs


class AlertTestMixin(BaseTest):
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
            alert = ErrorTrackingAlert.objects.create(
                team=self.team,
                name="Notify #alerts",
                enabled=enabled,
                triggers=triggers if triggers is not None else ["issue_created"],
            )
            alert.destinations.create(
                team=self.team,
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0123"},
            )
        return alert

    def _inputs(self, event: str, notification_id: str = "notif-1", **overrides) -> AlertDeliveryWorkflowInputs:
        defaults: dict[str, Any] = {
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


class TestAlertDeliveryPlanning(AlertTestMixin):
    @parameterized.expand(
        [
            ("issue_created", "$error_tracking_issue_created"),
            ("issue_reopened", "$error_tracking_issue_reopened"),
            ("issue_spiking", "$error_tracking_issue_spiking"),
            ("issue_assigned", "$error_tracking_issue_assigned"),
        ]
    )
    def test_subscribed_opener_is_planned(self, trigger, event):
        alert = self._create_alert(triggers=[trigger])

        planned = plan_alert_deliveries(self._inputs(event))

        assert len(planned) == 1
        assert planned[0].alert.id == alert.id
        assert planned[0].is_opener is True
        assert planned[0].thread is None

    @parameterized.expand(
        [
            ("trigger_not_subscribed", {"triggers": ["issue_spiking"]}),
            ("alert_disabled", {"enabled": False}),
        ]
    )
    def test_non_matching_alert_is_not_planned(self, _name, alert_kwargs):
        self._create_alert(**alert_kwargs)

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_created"))

        assert planned == []

    def test_reply_without_thread_is_not_planned(self):
        # Replies never open threads: resolved is not an opener trigger.
        self._create_alert(triggers=["issue_created"])

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))

        assert planned == []

    def test_reply_follows_existing_thread(self):
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            thread = ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=alert.destinations.first(),
            )

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))

        assert len(planned) == 1
        assert planned[0].is_opener is False
        assert planned[0].thread is not None
        assert planned[0].thread.id == thread.id


class TestAlertDeliveryDispatch(AlertTestMixin):
    def _dispatch(self) -> None:
        start_alert_delivery_workflow(
            team_id=self.team.id,
            event="$error_tracking_issue_created",
            issue_id=str(self.issue.id),
            notification_id="notif-1",
        )

    def test_dispatch_skips_teams_without_enabled_alerts(self):
        self._create_alert(enabled=False)
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.sync_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True) as flag,
        ):
            self._dispatch()
        connect.assert_not_called()
        # The row gate runs first, so teams without alerts never evaluate the flag.
        flag.assert_not_called()

    def test_dispatch_skips_teams_outside_the_flag(self):
        self._create_alert()
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.sync_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=False),
        ):
            self._dispatch()
        connect.assert_not_called()

    def test_dispatch_starts_idempotent_workflow(self):
        self._create_alert()
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.sync_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            connect.return_value.start_workflow = AsyncMock()
            self._dispatch()

        connect.return_value.start_workflow.assert_called_once()
        args, kwargs = connect.return_value.start_workflow.call_args
        assert args[0] == "error-tracking-alert-delivery"
        assert args[1].notification_id == "notif-1"
        assert kwargs["id"] == "error-tracking-alert-delivery-notif-1"

    def test_dispatch_swallows_temporal_errors(self):
        self._create_alert()
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.sync_connect",
                side_effect=RuntimeError("temporal down"),
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            self._dispatch()
