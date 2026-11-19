from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.db import DatabaseError
from django.test import override_settings

from parameterized import parameterized

from posthog.models import OrganizationMembership, Team
from posthog.models.instance_setting import override_instance_config

from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.workflows.backend.services import email_sending_tier_notifications
from products.workflows.backend.services.email_sending_tier import TierDecision


@override_settings(
    WORKFLOWS_EMAIL_TIER_DAILY_CAPS=[100, 1000, 5000, 20000],
    WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS=[100, 1000, 5000, 20000],
)
class TestNotifyEmailSendingTierChanges(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _demotion(self, reason: str) -> TierDecision:
        return TierDecision(team_id=self.team.id, previous_tier=3, new_tier=2, reason=reason)

    def _promotion(self, team_id: int | None = None) -> TierDecision:
        return TierDecision(team_id=team_id or self.team.id, previous_tier=2, new_tier=3, reason="clean_and_used")

    def _delivered_html(self) -> str:
        message = mail.outbox[0]
        assert isinstance(message, EmailMultiAlternatives)
        return str(message.alternatives[0][0])

    def _assert_nothing_reached_anyone(self) -> None:
        assert stored_notifications_for_team(self.team.id) == []
        assert mail.outbox == []

    @parameterized.expand([("off",), ("shadow",)])
    def test_nothing_fires_until_the_mode_is_enforce(self, mode: str) -> None:
        with override_settings(WORKFLOWS_EMAIL_TIER_MODE=mode):
            email_sending_tier_notifications.notify_email_sending_tier_changes(
                [self._demotion("rates_above_threshold"), self._promotion()]
            )
        self._assert_nothing_reached_anyone()

    @parameterized.expand([("rates_above_threshold",), ("workflow_auto_paused",), ("ses_reputation_high",)])
    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_rate_demotion_notifies_in_app_and_by_email(self, reason: str) -> None:
        email_sending_tier_notifications.notify_email_sending_tier_changes([self._demotion(reason)])

        [notification] = stored_notifications_for_team(self.team.id)
        assert notification.notification_type == "email_reputation"
        assert notification.title == "Workflow email sending limit lowered"
        assert "this project's limit is now 5,000 emails per day" in notification.body
        assert (notification.target_type, notification.target_id) == ("team", str(self.team.id))
        assert notification.resolved_user_ids == [self.user.id]

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == [self.user.email]
        assert email.subject == f"Workflow email sending limit lowered for project '{self.team}'"
        assert "5,000 emails per day" in self._delivered_html()

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_promotion_notifies_in_app_only(self) -> None:
        email_sending_tier_notifications.notify_email_sending_tier_changes([self._promotion()])

        [notification] = stored_notifications_for_team(self.team.id)
        assert notification.notification_type == "email_reputation"
        assert notification.title == "Workflow email sending limit raised"
        assert "up to 20,000 emails per day" in notification.body
        assert (notification.target_type, notification.target_id) == ("team", str(self.team.id))
        assert notification.resolved_user_ids == [self.user.id]
        assert mail.outbox == []

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
        email_sending_tier_notifications.notify_email_sending_tier_changes(
            [TierDecision(team_id=self.team.id, previous_tier=previous, new_tier=new, reason=reason)]
        )
        self._assert_nothing_reached_anyone()

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_one_failing_notification_does_not_stop_the_rest(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        create_notification = email_sending_tier_notifications.create_notification
        write_failures = [DatabaseError("notification write failed")]

        def _fail_first_write(data):
            if write_failures:
                raise write_failures.pop()
            return create_notification(data)

        with patch.object(email_sending_tier_notifications, "create_notification", side_effect=_fail_first_write):
            email_sending_tier_notifications.notify_email_sending_tier_changes(
                [self._demotion("rates_above_threshold"), self._promotion(team_id=other_team.id)]
            )

        assert stored_notifications_for_team(self.team.id) == []
        assert [n.title for n in stored_notifications_for_team(other_team.id)] == [
            "Workflow email sending limit raised"
        ]
        # The demotion email must survive the in-app failure: it reaches the admins who can act.
        assert len(mail.outbox) == 1
        assert "5,000 emails per day" in self._delivered_html()
