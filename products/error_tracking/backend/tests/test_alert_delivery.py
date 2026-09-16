import time
import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertThread, ErrorTrackingIssue
from products.error_tracking.backend.tasks.tasks import dispatch_error_tracking_alert_deliveries
from products.error_tracking.backend.temporal.alerts.delivery import deliver_alert_notifications, plan_alert_deliveries
from products.error_tracking.backend.temporal.alerts.dispatch import (
    AlertDispatchError,
    start_alert_delivery_workflow,
    start_alert_delivery_workflows,
)
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
                destination=alert.destinations.get(),
            )

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))

        assert len(planned) == 1
        assert planned[0].is_opener is False
        assert planned[0].thread is not None
        assert planned[0].thread.id == thread.id

    def test_repeated_opener_event_with_thread_is_a_reply(self):
        alert = self._create_alert(triggers=["issue_created", "issue_reopened"])
        with team_scope(self.team.id):
            ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=alert.destinations.get(),
            )

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_reopened"))

        assert len(planned) == 1
        assert planned[0].is_opener is False
        assert planned[0].thread is not None

    def test_multi_destination_alert_plans_per_destination(self):
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            first_destination = alert.destinations.get()
            second_destination = alert.destinations.create(
                team=self.team,
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0456"},
            )
            # Only the second destination has a rooted thread for this issue.
            thread = ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=second_destination,
            )

        opener = plan_alert_deliveries(self._inputs("$error_tracking_issue_created"))
        assert len(opener) == 2
        assert {planned.destination.id for planned in opener} == {first_destination.id, second_destination.id}

        reply = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))
        assert len(reply) == 1
        assert reply[0].destination.id == second_destination.id
        assert reply[0].thread is not None
        assert reply[0].thread.id == thread.id

    def test_planned_delivery_is_reported_through_the_real_logger(self):
        # The planning log runs structlog with the real processor chain: a kwarg
        # that collides with structlog's positional `event` raises on every
        # planned destination and fails the whole activity.
        self._create_alert(triggers=["issue_created"])

        assert deliver_alert_notifications(self._inputs("$error_tracking_issue_created")) == 1


class TestAlertDeliveryDispatch(AlertTestMixin):
    def _dispatch(self, *notification_ids: str) -> None:
        batch = [
            self._inputs("$error_tracking_issue_created", notification_id=nid)
            for nid in notification_ids or ("notif-1",)
        ]
        start_alert_delivery_workflows(batch)

    def _temporal(self, start_workflow: AsyncMock | None = None) -> MagicMock:
        client = MagicMock()
        client.start_workflow = start_workflow or AsyncMock()
        return client

    def test_dispatch_skips_teams_without_enabled_alerts(self):
        self._create_alert(enabled=False)
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True) as flag,
        ):
            self._dispatch()
        connect.assert_not_called()
        # The row gate runs first, so teams without alerts never evaluate the flag.
        flag.assert_not_called()

    def test_dispatch_skips_teams_outside_the_flag(self):
        self._create_alert()
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=False),
        ):
            self._dispatch()
        connect.assert_not_called()

    def test_dispatch_starts_idempotent_workflow(self):
        self._create_alert()
        client = self._temporal()
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                new_callable=AsyncMock,
                return_value=client,
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            start_alert_delivery_workflow(self._inputs("$error_tracking_issue_created"))

        client.start_workflow.assert_called_once()
        args, kwargs = client.start_workflow.call_args
        assert args[0] == "error-tracking-alert-delivery"
        assert args[1].notification_id == "notif-1"
        assert kwargs["id"] == "error-tracking-alert-delivery-notif-1"
        # Delivery must never ride the lifecycle fleet: slow Slack retries would starve issue-state work.
        assert kwargs["task_queue"] == settings.ERROR_TRACKING_TASK_QUEUE
        # A redelivered start after completion must be rejected, not rerun.
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY

    def test_batch_shares_one_connection_and_tolerates_already_started(self):
        self._create_alert()
        client = self._temporal(AsyncMock(side_effect=[None, WorkflowAlreadyStartedError("id", "type"), None]))
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                new_callable=AsyncMock,
                return_value=client,
            ) as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True) as flag,
        ):
            self._dispatch("n-1", "n-2", "n-3")

        connect.assert_awaited_once()
        flag.assert_called_once()
        assert client.start_workflow.await_count == 3
        assert {call.kwargs["id"] for call in client.start_workflow.call_args_list} == {
            "error-tracking-alert-delivery-n-1",
            "error-tracking-alert-delivery-n-2",
            "error-tracking-alert-delivery-n-3",
        }

    def test_batch_raises_when_any_start_is_not_accepted(self):
        # The caller retries the whole batch; accepted starts are idempotent, so only the
        # rejected one takes effect on the retry.
        self._create_alert()
        client = self._temporal(AsyncMock(side_effect=[None, RuntimeError("temporal hiccup")]))
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                new_callable=AsyncMock,
                return_value=client,
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
            self.assertRaises(AlertDispatchError),
        ):
            self._dispatch("n-1", "n-2")

    def test_batch_rejects_mixed_teams(self):
        other = self._inputs("$error_tracking_issue_created", notification_id="n-2", team_id=self.team.id + 1)
        with self.assertRaises(ValueError):
            start_alert_delivery_workflows([self._inputs("$error_tracking_issue_created"), other])

    def test_dispatch_gives_up_on_a_stalled_temporal(self):
        self._create_alert()

        async def hang() -> None:
            await asyncio.sleep(5)

        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect", side_effect=hang),
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.DISPATCH_TIMEOUT", timedelta(milliseconds=50)
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                self._dispatch()

        # The caller gets control back well before the stalled connect would return, and retries.
        assert time.monotonic() - started < 2

    def test_dispatch_raises_temporal_errors_for_the_caller_to_retry(self):
        self._create_alert()
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                side_effect=RuntimeError("temporal down"),
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
            self.assertRaises(RuntimeError),
        ):
            self._dispatch()

    def test_celery_task_rebuilds_inputs_and_starts_the_batch(self):
        notifications = [
            dataclasses.asdict(self._inputs("$error_tracking_issue_resolved", notification_id="n-1")),
            dataclasses.asdict(self._inputs("$error_tracking_issue_resolved", notification_id="n-2")),
        ]
        with patch("products.error_tracking.backend.temporal.alerts.dispatch.start_alert_delivery_workflows") as start:
            dispatch_error_tracking_alert_deliveries(team_id=self.team.id, notifications=notifications)

        start.assert_called_once()
        (batch,) = start.call_args.args
        assert [inputs.notification_id for inputs in batch] == ["n-1", "n-2"]
        assert all(isinstance(inputs, AlertDeliveryWorkflowInputs) for inputs in batch)
