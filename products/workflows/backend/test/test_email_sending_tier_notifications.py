from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.workflows.backend.services.email_sending_tier import TierDecision
from products.workflows.backend.services.email_sending_tier_notifications import notify_email_sending_tier_changes

NOTIFICATIONS_MODULE = "products.workflows.backend.services.email_sending_tier_notifications"


def _demotion(reason: str) -> TierDecision:
    return TierDecision(team_id=1, previous_tier=3, new_tier=2, reason=reason)


def _promotion() -> TierDecision:
    return TierDecision(team_id=1, previous_tier=2, new_tier=3, reason="clean_and_used")


class TestNotifyEmailSendingTierChanges(SimpleTestCase):
    def setUp(self) -> None:
        create_patch = patch(f"{NOTIFICATIONS_MODULE}.create_notification")
        email_patch = patch(f"{NOTIFICATIONS_MODULE}.send_email_sending_tier_demoted")
        self.create_notification = create_patch.start()
        self.email_task = email_patch.start()
        self.addCleanup(create_patch.stop)
        self.addCleanup(email_patch.stop)

    @parameterized.expand([("off",), ("shadow",)])
    def test_nothing_fires_until_the_mode_is_enforce(self, mode: str) -> None:
        with override_settings(WORKFLOWS_EMAIL_TIER_MODE=mode):
            notify_email_sending_tier_changes([_demotion("rates_above_threshold"), _promotion()])
        self.create_notification.assert_not_called()
        self.email_task.delay.assert_not_called()

    @parameterized.expand([("rates_above_threshold",), ("workflow_auto_paused",), ("ses_reputation_high",)])
    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_rate_demotion_notifies_in_app_and_by_email(self, reason: str) -> None:
        notify_email_sending_tier_changes([_demotion(reason)])
        assert self.create_notification.call_count == 1
        data = self.create_notification.call_args.args[0]
        assert data.title == "Workflow email sending limit lowered"
        assert data.team_id == 1
        assert self.email_task.delay.call_count == 1
        assert self.email_task.delay.call_args.kwargs["team_id"] == 1

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_promotion_notifies_in_app_only(self) -> None:
        notify_email_sending_tier_changes([_promotion()])
        assert self.create_notification.call_count == 1
        assert self.create_notification.call_args.args[0].title == "Workflow email sending limit raised"
        self.email_task.delay.assert_not_called()

    @parameterized.expand(
        [
            ("inactive", 3, 2),
            ("ses_tenant_paused", 3, 0),
            ("staff_suspension", 3, 0),
            ("demotion_cooldown", 3, 3),
        ]
    )
    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_decay_suspensions_and_holds_stay_silent(self, reason: str, previous: int, new: int) -> None:
        notify_email_sending_tier_changes(
            [TierDecision(team_id=1, previous_tier=previous, new_tier=new, reason=reason)]
        )
        self.create_notification.assert_not_called()
        self.email_task.delay.assert_not_called()

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_one_failing_notification_does_not_stop_the_rest(self) -> None:
        self.create_notification.side_effect = [Exception("kafka down"), None]
        second = TierDecision(team_id=2, previous_tier=2, new_tier=3, reason="clean_and_used")
        notify_email_sending_tier_changes([_demotion("rates_above_threshold"), second])
        assert self.create_notification.call_count == 2
        assert self.create_notification.call_args.args[0].team_id == 2
        # The demotion email must survive the in-app failure: it reaches the admins who can act.
        assert self.email_task.delay.call_count == 1
