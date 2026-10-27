from datetime import date

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.tasks.email import DEFAULT_TIER_DEMOTION_CAUSE

from products.workflows.backend.facade.contracts import TierDemotionEvidence
from products.workflows.backend.services.email_sending_tier import TierDecision
from products.workflows.backend.services.email_sending_tier_notifications import notify_email_sending_tier_changes

NOTIFICATIONS_MODULE = "products.workflows.backend.services.email_sending_tier_notifications"


def _demotion(reason: str, evidence: TierDemotionEvidence | None = None) -> TierDecision:
    return TierDecision(team_id=1, previous_tier=3, new_tier=2, reason=reason, evidence=evidence)


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

    @parameterized.expand(
        [
            (
                "rates_above_threshold",
                TierDemotionEvidence(since=date(2026, 3, 2), sent=1240, complained=4, hard_bounced=1),
                "Since March 2, this project sent 1,240 workflow emails and got 4 spam complaints and 1 hard bounce.",
            ),
            (
                "rates_above_threshold",
                TierDemotionEvidence(since=date(2026, 3, 2), sent=0, complained=3, hard_bounced=0),
                "Since March 2, this project got 3 spam complaints and 0 hard bounces about workflow emails it sent before then.",
            ),
            ("rates_above_threshold", None, DEFAULT_TIER_DEMOTION_CAUSE),
            ("workflow_auto_paused", None, "A workflow in this project was paused automatically"),
            ("ses_reputation_high", None, "Our email provider flagged this project's sending reputation."),
        ]
    )
    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_rate_demotion_notifies_in_app_and_by_email_with_its_cause(
        self, reason: str, evidence: TierDemotionEvidence | None, expected_cause: str
    ) -> None:
        notify_email_sending_tier_changes([_demotion(reason, evidence)])
        assert self.create_notification.call_count == 1
        data = self.create_notification.call_args.args[0]
        assert data.title == "Workflow email sending limit lowered"
        assert data.team_id == 1
        assert expected_cause in data.body
        assert self.email_task.delay.call_count == 1
        assert self.email_task.delay.call_args.kwargs["team_id"] == 1
        assert expected_cause in self.email_task.delay.call_args.kwargs["cause"]

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
