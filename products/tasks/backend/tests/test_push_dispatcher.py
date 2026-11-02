from contextlib import nullcontext
from uuid import uuid4

import time_machine
from unittest.mock import Mock, patch

from django.db import InterfaceError, OperationalError, transaction
from django.test import TestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.user_push_token import UserPushToken
from posthog.tasks.push_notifications import send_user_push

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import append_task_run_artefact
from products.tasks.backend.awaiting_input import dispatch_awaiting_input
from products.tasks.backend.mobile_push import mobile_push_user_ids, record_mobile_pickup
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.push_dispatcher import (
    notify_task_handoff,
    notify_task_pull_request_outcome,
    notify_task_run_awaiting_input,
    notify_task_run_cancelled,
    notify_task_run_completed,
    notify_task_run_failed,
    notify_task_run_turn_completed,
)
from products.tasks.backend.redis import get_tasks_cache


# The Celery dispatch is deferred via transaction.on_commit, which never fires
# inside TestCase's rolled-back transaction — tests wrap notify calls in
# captureOnCommitCallbacks(execute=True) to run the deferred callback (or assert
# none was registered) without TransactionTestCase's per-test full-DB flush.
class TestPushDispatcher(TestCase):
    def setUp(self) -> None:
        get_tasks_cache().clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="push@example.com", first_name="Push", password="password")
        # Push dispatch requires the recipient to still be a member of the team's org —
        # see the access check in push_dispatcher._enqueue.
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.task = Task.objects.create(
            team=self.team,
            title="My Task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            state={"created_on_mobile": True},
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)

    @parameterized.expand(
        [
            ("completed", notify_task_run_completed, "finished"),
            ("failed", notify_task_run_failed, "failed"),
            ("cancelled", notify_task_run_cancelled, "cancelled"),
            ("awaiting", notify_task_run_awaiting_input, "needs your input"),
            ("turn_completed", notify_task_run_turn_completed, "finished"),
        ]
    )
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_notify_enqueues_push(self, _name, notify_fn, expected_body_fragment, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            notify_fn(self.task_run)
        mock_delay.assert_called_once()
        user_id, title, body, data, suppressed = mock_delay.call_args.args
        self.assertEqual(user_id, self.user.id)
        self.assertEqual(title, "PostHog")
        self.assertIn(expected_body_fragment, body)
        self.assertEqual(data["taskId"], str(self.task.id))
        self.assertEqual(data["projectId"], self.task.team_id)
        self.assertEqual(data["taskRunId"], str(self.task_run.id))
        self.assertEqual(data["notificationKind"], _name)
        # No presence rows in this test's setUp, so nothing to suppress.
        self.assertEqual(suppressed, [])

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_trial_completion_does_not_notify_the_operator(self, mock_delay) -> None:
        self.task.origin_product = Task.OriginProduct.SIGNALS_SCOUT
        self.task.origin_key = f"scout-trial:{uuid4()}"
        self.task.save(update_fields=["origin_product", "origin_key"])

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)

        mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_collapses_duplicates(self, mock_delay):
        labels = {"kind": "completed", "outcome": "cooldown_deduped"}
        before = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_outcomes_total", labels) or 0.0
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
        self.assertEqual(mock_delay.call_count, 1)
        after = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_outcomes_total", labels) or 0.0
        self.assertEqual(after, before + 2)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_is_per_kind(self, mock_delay):
        # Different push kinds on the same run shouldn't share a cooldown key.
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_awaiting_input(self.task_run)
            notify_task_run_turn_completed(self.task_run)
        self.assertEqual(mock_delay.call_count, 3)

    def _link_report_work(self, relationship: str) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, first_visible_at="2026-10-20T12:00:00Z"
        )
        self.task.signal_report = report
        self.task.save(update_fields=["signal_report"])
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type=relationship,
            task_id=str(self.task.id),
            run_id=str(self.task_run.id),
        )

    @parameterized.expand([None, "implementation", "research"])
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    @patch("products.signals.backend.inbox_push_notifications.posthoganalytics.feature_enabled", return_value=True)
    def test_awaiting_cooldown_is_shared_by_permission_requests_and_turn_end(
        self, relationship: str | None, _flag: Mock, mock_delay: Mock
    ) -> None:
        self.task_run.state = {"mode": "interactive"}
        with time_machine.travel("2026-10-20T12:00:00Z", tick=False) as clock:
            if relationship is not None:
                self._link_report_work(relationship)
            with self.captureOnCommitCallbacks(execute=True):
                dispatch_awaiting_input(self.task_run, request_id="request-1")
                dispatch_awaiting_input(self.task_run, request_id="request-2")
                notify_task_run_awaiting_input(self.task_run)
            self.assertEqual(mock_delay.call_count, 1)

            clock.shift(31)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertFalse(dispatch_awaiting_input(self.task_run, request_id="request-1"))
                self.assertTrue(dispatch_awaiting_input(self.task_run, request_id="request-3"))
            self.assertEqual(mock_delay.call_count, 2)
            self.assertEqual(mock_delay.call_args.args[3]["type"], "report" if relationship else "task")

    @parameterized.expand(
        [(failure, None) for failure in ("prepare", "immediate", "deferred", "rollback")]
        + [
            (failure, relationship)
            for failure in ("immediate", "deferred", "rollback")
            for relationship in ("implementation", "research")
        ]
    )
    def test_awaiting_request_can_retry_after_failed_enqueue(self, failure: str, relationship: str | None) -> None:
        self.task_run.state = {"mode": "interactive"}
        with (
            time_machine.travel("2026-10-20T12:00:00Z", tick=False) as clock,
            patch(
                "products.signals.backend.inbox_push_notifications.posthoganalytics.feature_enabled", return_value=True
            ),
            patch("products.tasks.backend.push_dispatcher._project_awaiting_input_activity"),
            patch("products.tasks.backend.push_dispatcher.send_user_push.delay") as send_push,
        ):
            if relationship is not None:
                self._link_report_work(relationship)
            send_push.side_effect = RuntimeError("broker unavailable")
            with (
                patch(
                    "products.tasks.backend.push_dispatcher.suppressed_push_token_ids_for_task",
                    side_effect=OperationalError("connection unavailable"),
                )
                if failure == "prepare"
                else nullcontext(),
                patch("products.tasks.backend.push_dispatcher.transaction.on_commit", side_effect=lambda fn, **_: fn())
                if failure == "immediate"
                else nullcontext(),
                self.captureOnCommitCallbacks(execute=True),
                transaction.atomic(),
            ):
                scheduled = dispatch_awaiting_input(self.task_run, request_id="retry-request")
                self.assertEqual(scheduled, relationship is not None or failure in ("deferred", "rollback"))
                if failure == "rollback":
                    transaction.set_rollback(True)
            self.assertEqual(send_push.call_count, int(failure in ("immediate", "deferred")))

            clock.shift(31)
            send_push.reset_mock()
            send_push.side_effect = None
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(dispatch_awaiting_input(self.task_run, request_id="retry-request"))
                send_push.assert_not_called()
            send_push.assert_called_once()

            clock.shift(31)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertFalse(dispatch_awaiting_input(self.task_run, request_id="retry-request"))
            send_push.assert_called_once()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_handoff_cooldown_distinguishes_announcements(self, mock_delay):
        announcement_id = uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=announcement_id)
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=announcement_id)
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=uuid4())
        self.assertEqual(mock_delay.call_count, 2)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_recipient_without_team_access_is_skipped(self, mock_delay):
        """A user who has been removed from the task's organization must not receive
        pushes carrying that task's title — losing access should mean losing notifications."""
        outsider = User.objects.create_user(email="outsider@example.com", first_name="Out", password="x")
        outsider_task = Task.objects.create(
            team=self.team,
            title="Sensitive Task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=outsider,
        )
        outsider_run = TaskRun.objects.create(task=outsider_task, team=self.team)

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(outsider_run)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_anonymous_task_is_noop(self, mock_delay):
        anonymous_task = Task.objects.create(
            team=self.team,
            title="Anon",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=None,
        )
        anonymous_run = TaskRun.objects.create(task=anonymous_task, team=self.team)
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(anonymous_run)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher._enqueue_inner", side_effect=RuntimeError("redis is down"))
    def test_enqueue_swallows_unexpected_errors(self, _mock_inner):
        """The dispatcher MUST NOT raise. Any DB / Redis hiccup
        must be swallowed so it can't fail the task lifecycle activity that
        triggered the push."""
        # The bare except in _enqueue should catch the RuntimeError. If it
        # doesn't, this test raises and fails — which is the regression signal.
        notify_task_run_completed(self.task_run)

    @parameterized.expand(
        [
            (
                "db_connection_operational",
                "db_connection",
                OperationalError("server closed the connection unexpectedly"),
            ),
            ("db_connection_interface", "db_connection", InterfaceError("connection already closed")),
            ("other", "other", RuntimeError("redis is down")),
        ]
    )
    def test_swallowed_failure_increments_metric(self, _name, expected_reason, exc):
        labels = {"kind": "completed", "reason": expected_reason}
        before = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_failures_total", labels) or 0.0
        with patch("products.tasks.backend.push_dispatcher._enqueue_inner", side_effect=exc):
            notify_task_run_completed(self.task_run)
        after = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_failures_total", labels) or 0.0
        self.assertEqual(after, before + 1)

    @parameterized.expand(
        [
            ("web", {}, Task.OriginProduct.USER_CREATED),
            ("web_later_run_mobile", {"created_on_mobile": False}, Task.OriginProduct.USER_CREATED),
            ("slack", {"created_on_mobile": True}, Task.OriginProduct.SLACK),
        ]
    )
    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_nonmobile_tasks_never_enqueue(self, _name, state, origin, mock_delay, _flag):
        self.task.state = state
        self.task.origin_product = origin
        self.task.save(update_fields=["state", "origin_product"])
        self.task_run.state = {"client_platform": "mobile"}
        self.task_run.save(update_fields=["state"])
        with self.captureOnCommitCallbacks(execute=True):
            for notify in (
                notify_task_run_completed,
                notify_task_run_failed,
                notify_task_run_cancelled,
                notify_task_run_awaiting_input,
                notify_task_run_turn_completed,
            ):
                notify(self.task_run)
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=uuid4())
        mock_delay.assert_not_called()

    @parameterized.expand([("mobile_push_enabled",), ("mobile_push_tasks_enabled",)])
    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    @patch("posthog.tasks.push_notifications.send_push_to_user")
    def test_preferences_stop_new_and_queued_pushes(self, key, mock_send, mock_delay, _flag):
        self.user.partial_notification_settings = {key: False}
        self.user.save(update_fields=["partial_notification_settings"])
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
        send_user_push(
            self.user.id, "PostHog", "Finished", {"taskId": str(self.task.id), "projectId": self.task.team_id}
        )
        mock_delay.assert_not_called()
        mock_send.assert_not_called()

    @parameterized.expand(
        [
            ("web_active", Task.OriginProduct.USER_CREATED, True),
            ("web_inactive", Task.OriginProduct.USER_CREATED, False),
            ("slack_active", Task.OriginProduct.SLACK, True),
            ("slack_inactive", Task.OriginProduct.SLACK, False),
        ]
    )
    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    @patch("posthog.push_notifications.requests.post")
    def test_mobile_pickup_enables_existing_task_and_queued_delivery(
        self, _name: str, origin: str, is_active: bool, mock_post: Mock, mock_delay: Mock, _flag: Mock
    ) -> None:
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[mobile-pickup]", platform="ios")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"data": [{"status": "ok"}]}
        self.task.origin_product = origin
        self.task.state = {"created_on_mobile": False}
        self.task.save(update_fields=["origin_product", "state"])
        record_mobile_pickup(task_id=self.task.id, team_id=self.team.id, user_id=self.user.id)
        record_mobile_pickup(task_id=self.task.id, team_id=self.team.id, user_id=self.user.id)
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
        mock_delay.assert_called_once()
        User.objects.filter(id=self.user.id).update(is_active=is_active)
        send_user_push(*mock_delay.call_args.args)
        if is_active:
            mock_post.assert_called_once()
        else:
            mock_post.assert_not_called()
        self.task.refresh_from_db()
        self.assertEqual(mobile_push_user_ids(self.task), {self.user.id})
        self.assertIs(self.task.state["created_on_mobile"], False)

    @parameterized.expand([None, "enqueue", "delivery"])
    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    @patch("posthog.push_notifications.requests.post")
    def test_mobile_pickup_fanout_is_per_user_and_refreshes_cached_task(
        self, revoke_at: str | None, mock_post: Mock, mock_delay: Mock, _flag: Mock
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="task", access_level="none")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"data": [{"status": "ok"}]}
        self.task.origin_product = Task.OriginProduct.WORKFLOW
        self.task.state = {}
        self.task.save(update_fields=["origin_product", "state"])
        picked = [
            User.objects.create_and_join(self.organization, f"picked-{index}@example.com", None) for index in range(2)
        ]
        for user in picked:
            record_mobile_pickup(task_id=self.task.id, team_id=self.team.id, user_id=user.id)
            AccessControl.objects.create(
                team=self.team,
                resource="task",
                organization_member=OrganizationMembership.objects.get(organization=self.organization, user=user),
                access_level="viewer",
            )
            UserPushToken.objects.create(user=user, token=f"ExponentPushToken[picked-{user.id}]", platform="ios")

        def revoke_access() -> None:
            AccessControl.objects.filter(team=self.team, resource="task", organization_member__user=picked[0]).update(
                access_level="none"
            )

        if revoke_at == "enqueue":
            revoke_access()
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
        enqueued_users = picked[1:] if revoke_at == "enqueue" else picked
        self.assertEqual({call.args[0] for call in mock_delay.call_args_list}, {user.id for user in enqueued_users})
        self.assertEqual(mock_delay.call_count, len(enqueued_users))
        if revoke_at == "delivery":
            revoke_access()
        for call in mock_delay.call_args_list:
            send_user_push(*call.args)
        delivered_users = picked if revoke_at is None else picked[1:]
        self.assertEqual(
            {call.kwargs["json"][0]["to"] for call in mock_post.call_args_list},
            {f"ExponentPushToken[picked-{user.id}]" for user in delivered_users},
        )

    @parameterized.expand(
        [
            (outcome, merged, failure)
            for outcome, merged in [("merged", True), ("closed", False)]
            for failure in (None, "redis", "broker", "rollback")
        ]
    )
    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_pr_outcomes_are_durable_per_user_and_pr(self, outcome, merged, failure, mock_delay, _flag):
        self.task.origin_product = Task.OriginProduct.SLACK
        self.task.state = {"mobile_push_user_ids": [self.user.id]}
        self.task.save(update_fields=["origin_product", "state"])
        pr_url = "https://github.com/example/project/pull/1"
        if failure is not None:

            def notify() -> None:
                notify_task_pull_request_outcome(
                    task_id=str(self.task.id),
                    run_id=str(self.task_run.id),
                    team_id=self.team.id,
                    pr_url=pr_url,
                    merged=merged,
                )

            if failure == "rollback":
                with self.captureOnCommitCallbacks(execute=True):
                    with self.assertRaises(RuntimeError), transaction.atomic():
                        notify()
                        raise RuntimeError("rollback")
            else:
                boundary = (
                    patch.object(get_tasks_cache(), "add", side_effect=RuntimeError("redis unavailable"))
                    if failure == "redis"
                    else patch.object(mock_delay, "side_effect", RuntimeError("broker unavailable"))
                )
                with boundary, self.captureOnCommitCallbacks(execute=True):
                    notify()
            self.task.refresh_from_db()
            self.assertEqual((self.task.state or {}).get("mobile_push_pr_outcomes", []), [])
            mock_delay.reset_mock(side_effect=True)
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                notify_task_pull_request_outcome(
                    task_id=str(self.task.id),
                    run_id=str(self.task_run.id),
                    team_id=self.team.id,
                    pr_url=pr_url,
                    merged=merged,
                )
            get_tasks_cache().clear()
        mock_delay.assert_called_once()
        self.assertEqual(mock_delay.call_args.args[1:3], ("PostHog", f'"My Task" pull request was {outcome}'))
        self.assertEqual(mock_delay.call_args.args[3]["pullRequestUrl"], pr_url)
        self.assertEqual(mock_delay.call_args.args[3]["notificationKind"], f"pr_{outcome}")
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_pull_request_outcome(
                task_id=str(self.task.id),
                run_id=str(self.task_run.id),
                team_id=self.team.id,
                pr_url="https://github.com/example/project/pull/2",
                merged=merged,
            )
        self.assertEqual(mock_delay.call_count, 2)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_completed")
    def test_mark_completed_triggers_push(self, mock_notify):
        self.task_run.mark_completed()
        mock_notify.assert_called_once_with(self.task_run)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_failed")
    def test_mark_failed_triggers_push(self, mock_notify):
        self.task_run.mark_failed("nope")
        mock_notify.assert_called_once_with(self.task_run)

    @patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.tasks.push_notifications.send_push_to_user", return_value=2)
    def test_delivery_task_records_expo_acceptance(self, mock_send, _flag):
        labels = {"kind": "completed", "outcome": "accepted"}
        before = REGISTRY.get_sample_value("posthog_push_delivery_outcomes_total", labels) or 0.0

        send_user_push(
            self.user.id,
            "posthog",
            "Finished",
            {"notificationKind": "completed", "taskId": str(self.task.id), "projectId": self.task.team_id},
        )

        mock_send.assert_called_once()
        after = REGISTRY.get_sample_value("posthog_push_delivery_outcomes_total", labels) or 0.0
        self.assertEqual(after, before + 1)
