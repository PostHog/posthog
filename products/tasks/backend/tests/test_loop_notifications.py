from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from products.tasks.backend.loop_notifications import _channel_enabled, dispatch_loop_event
from products.tasks.backend.models import Loop

LOOP_NOTIFICATIONS_MODULE = "products.tasks.backend.loop_notifications"


class TestChannelEnabled(SimpleTestCase):
    @parameterized.expand(
        [
            ("enabled_and_subscribed", {"enabled": True, "events": ["run_completed"]}, "run_completed", True),
            ("enabled_but_not_subscribed", {"enabled": True, "events": ["run_failed"]}, "run_completed", False),
            ("disabled_but_subscribed", {"enabled": False, "events": ["run_completed"]}, "run_completed", False),
            ("disabled_and_not_subscribed", {"enabled": False, "events": []}, "run_completed", False),
            ("missing_enabled_key", {"events": ["run_completed"]}, "run_completed", False),
            ("missing_events_key", {"enabled": True}, "run_completed", False),
            ("empty_config", {}, "run_completed", False),
        ]
    )
    def test_channel_enabled_matrix(self, _name, channel_config, event, expected):
        self.assertEqual(_channel_enabled(channel_config, event), expected)


class LoopNotificationsTestCase(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="loop-owner@example.com", first_name="Loop", password="password")

    def create_loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Daily digest",
            "instructions": "Summarize open PRs across the team's repos",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-4-5",
            "enabled": True,
        }
        defaults.update(overrides)
        loop = Loop(**defaults)
        loop.save()
        return loop


class TestDispatchLoopEventInApp(LoopNotificationsTestCase):
    @parameterized.expand(
        [
            ("no_channels_configured", {}),
            (
                "all_channels_disabled",
                {
                    "push": {"enabled": False, "events": ["run_completed"]},
                    "email": {"enabled": False, "events": ["run_completed"]},
                    "slack": {"enabled": False, "events": ["run_completed"]},
                },
            ),
        ]
    )
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    def test_in_app_notification_dispatched_regardless_of_channel_config(
        self, _name, notifications, mock_create_notification
    ):
        loop = self.create_loop(notifications=notifications)

        dispatch_loop_event(loop, "run_completed", {"url": "https://example.com/run/1"})

        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        self.assertEqual(data.target_id, str(self.user.id))
        self.assertEqual(data.team_id, self.team.id)

    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    def test_in_app_notification_skipped_when_loop_has_no_owner(self, mock_create_notification):
        loop = self.create_loop(created_by=None)

        dispatch_loop_event(loop, "run_completed", {})

        mock_create_notification.assert_not_called()


class TestDispatchLoopEventCooldown(LoopNotificationsTestCase):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()
        self.addCleanup(self._clear_cooldown_keys)

    def _clear_cooldown_keys(self):
        for key in self.redis_client.scan_iter("loop_notifications:cooldown:*"):
            self.redis_client.delete(key)

    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.send_user_push.delay")
    def test_cooldown_drops_second_run_failed_within_window(self, mock_push_delay, mock_create_notification):
        loop = self.create_loop(notifications={"push": {"enabled": True, "events": ["run_failed"]}})

        with self.captureOnCommitCallbacks(execute=True):
            dispatch_loop_event(loop, "run_failed", {"reason": "boom"})
            dispatch_loop_event(loop, "run_failed", {"reason": "boom again"})

        self.assertEqual(mock_push_delay.call_count, 1)
        # In-app is cooldown-gated too: repeated failure/attention events (a capped or
        # crash-looping loop) must not write a notification row per fire.
        self.assertEqual(mock_create_notification.call_count, 1)

    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.send_user_push.delay")
    def test_run_completed_is_never_cooldown_gated(self, mock_push_delay, _mock_create_notification):
        loop = self.create_loop(notifications={"push": {"enabled": True, "events": ["run_completed"]}})

        with self.captureOnCommitCallbacks(execute=True):
            dispatch_loop_event(loop, "run_completed", {})
            dispatch_loop_event(loop, "run_completed", {})

        self.assertEqual(mock_push_delay.call_count, 2)


class TestDispatchLoopEventSlackErrors(LoopNotificationsTestCase):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"team": {"id": "T123"}},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def create_loop_with_slack(self, **overrides) -> Loop:
        notifications = {
            "slack": {
                "enabled": True,
                "events": ["run_completed"],
                "params": {"integration_id": self.integration.id, "channel": "C123"},
            }
        }
        return self.create_loop(notifications=notifications, **overrides)

    @parameterized.expand(
        [
            ("permanent_error_disables_channel", "channel_not_found", False, 2),
            ("transient_error_leaves_channel_enabled", "ratelimited", True, 1),
        ]
    )
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.SlackIntegration")
    def test_slack_error_handling_by_error_code(
        self,
        _name,
        error_code,
        expected_enabled,
        expected_notification_count,
        mock_slack_cls,
        mock_create_notification,
    ):
        loop = self.create_loop_with_slack()
        fake_client = MagicMock()
        fake_client.chat_postMessage.side_effect = SlackApiError(message="slack error", response={"error": error_code})
        mock_slack_cls.return_value.client = fake_client

        dispatch_loop_event(loop, "run_completed", {})

        loop.refresh_from_db()
        self.assertEqual(loop.notifications["slack"]["enabled"], expected_enabled)
        self.assertEqual(mock_create_notification.call_count, expected_notification_count)
        if not expected_enabled:
            disable_notification = mock_create_notification.call_args_list[1].args[0]
            self.assertIn("Slack notifications disabled", disable_notification.title)
            self.assertEqual(disable_notification.target_id, str(self.user.id))


class TestDispatchLoopEventChannelIsolation(LoopNotificationsTestCase):
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.send_user_push.delay")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.is_email_available", return_value=True)
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.EmailMessage")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.SlackIntegration")
    @patch(f"{LOOP_NOTIFICATIONS_MODULE}.create_notification")
    def test_email_channel_raising_does_not_block_push_or_slack(
        self,
        mock_create_notification,
        mock_slack_cls,
        mock_email_message_cls,
        _mock_email_available,
        mock_push_delay,
    ):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={},
            sensitive_config={"access_token": "xoxb-test"},
        )
        loop = self.create_loop(
            notifications={
                "push": {"enabled": True, "events": ["run_completed"]},
                "email": {"enabled": True, "events": ["run_completed"]},
                "slack": {
                    "enabled": True,
                    "events": ["run_completed"],
                    "params": {"integration_id": integration.id, "channel": "C1"},
                },
            }
        )
        mock_email_message_cls.side_effect = RuntimeError("smtp down")
        fake_slack_client = MagicMock()
        mock_slack_cls.return_value.client = fake_slack_client

        with self.captureOnCommitCallbacks(execute=True):
            dispatch_loop_event(loop, "run_completed", {})

        mock_push_delay.assert_called_once()
        mock_email_message_cls.assert_called_once()
        fake_slack_client.chat_postMessage.assert_called_once()
        # Only the original event's in-app notification: slack succeeded so no disable notice fired.
        mock_create_notification.assert_called_once()
