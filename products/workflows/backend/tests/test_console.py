import re

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.workflows.backend.facade.api import get_email_sending_state, suspend_email_sending
from products.workflows.backend.facade.contracts import TierDecision
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig

_RECOMPUTE = "products.workflows.backend.console.recompute_email_sending_tier"
_SUSPENSION = "products.workflows.backend.services.email_sending_suspension"


class TestEmailSendingConsolePanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _operation_url(self, operation_key: str) -> str:
        return f"/admin/console/teams/{self.team.pk}/email-sending/{operation_key}/"

    @parameterized.expand(
        [
            ("tier_change", {"tier": "2", "reason": "Raise"}, [("email_sending_tier", 1, 2)]),
            ("pin_only", {"tier": "1", "pinned": "on", "reason": "Hold"}, [("email_sending_tier_pinned", False, True)]),
            ("no_change", {"tier": "1", "reason": "Check"}, None),
        ]
    )
    def test_set_tier_audits_what_changed(
        self, _name: str, form: dict[str, str], expected_changes: list[tuple[str, object, object]] | None
    ) -> None:
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team, defaults={"email_sending_tier": 1, "email_sending_tier_pinned": False}
        )

        response = self.client.post(self._operation_url("set-tier"), form)

        assert response.status_code == 302
        entries = list(
            ActivityLog.objects.filter(scope="Team", team_id=self.team.id, activity="email_sending_tier_changed")
        )
        if expected_changes is None:
            assert entries == []
            return
        assert len(entries) == 1
        assert entries[0].user == self.user
        detail = entries[0].detail or {}
        assert detail["context"] == {"reason": "staff_set"}
        assert [(c["field"], c["before"], c["after"]) for c in detail["changes"]] == expected_changes

    def test_set_tier_form_starts_from_the_current_tier_and_pin(self) -> None:
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team, defaults={"email_sending_tier": 2, "email_sending_tier_pinned": True}
        )

        content = self.client.get(self._operation_url("set-tier")).content.decode()

        assert re.search(r'<option value="2"\s+selected>', content)
        assert re.search(r'name="pinned"[^>]*\bchecked\b', content)

    def test_set_tier_refuses_a_tier_outside_the_table(self) -> None:
        response = self.client.post(self._operation_url("set-tier"), {"tier": "99", "reason": "Raise"})

        assert response.status_code == 400
        assert not ActivityLog.objects.filter(activity="email_sending_tier_changed", team_id=self.team.id).exists()

    @patch(
        _RECOMPUTE,
        return_value=TierDecision(team_id=0, previous_tier=4, new_tier=4, reason="too_soon"),
    )
    def test_recompute_names_the_hold_reason_and_creates_a_missing_config(self, recompute: MagicMock) -> None:
        TeamWorkflowsConfig.objects.filter(team_id=self.team.pk).delete()

        response = self.client.post(self._operation_url("recompute-tier"), {"reason": "Customer asked"}, follow=True)

        recompute.assert_called_once_with(self.team.pk, user_id=self.user.pk, was_impersonated=False)
        assert TeamWorkflowsConfig.objects.filter(team_id=self.team.pk).exists()
        rendered = [str(message) for message in get_messages(response.wsgi_request)]
        content = response.content.decode() + " ".join(rendered)
        assert "keeps tier 4" in content
        assert "has not held its current tier" in content

    @patch(f"{_SUSPENSION}.create_notification")
    @patch(f"{_SUSPENSION}.send_email_sending_suspended")
    def test_suspend_drops_the_tier_audits_and_tells_the_team_once(
        self, send_email: MagicMock, create_notification: MagicMock
    ) -> None:
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team, defaults={"email_sending_tier": 3, "email_sending_tier_pinned": True}
        )

        response = self.client.post(self._operation_url("suspend"), {"reason": "Hard bounce rate above 5%"})
        repeat = suspend_email_sending(self.team.pk, "second", user_id=self.user.pk)

        assert response.status_code == 302
        assert repeat.previously_suspended_at is not None
        config = TeamWorkflowsConfig.objects.get(team_id=self.team.pk)
        assert config.email_sending_suspended_at is not None
        assert config.email_sending_suspension_reason == "Hard bounce rate above 5%"
        assert config.email_sending_tier == 0
        suspended = ActivityLog.objects.get(scope="Team", team_id=self.team.id, activity="email_sending_suspended")
        assert suspended.user == self.user
        assert (suspended.detail or {})["context"] == {"reason": "Hard bounce rate above 5%"}
        tier = ActivityLog.objects.get(scope="Team", team_id=self.team.id, activity="email_sending_tier_changed")
        assert (tier.detail or {})["context"] == {"reason": "staff_suspension"}
        send_email.delay.assert_called_once()
        assert send_email.delay.call_args.kwargs["reason"] == "Hard bounce rate above 5%"
        create_notification.assert_called_once()

    @patch(f"{_SUSPENSION}.create_notification")
    @patch(f"{_SUSPENSION}.send_email_sending_unsuspended")
    @patch(f"{_SUSPENSION}.send_email_sending_suspended")
    def test_unsuspend_clears_the_suspension_audits_and_tells_the_team(
        self, _send_suspended: MagicMock, send_unsuspended: MagicMock, create_notification: MagicMock
    ) -> None:
        suspend_email_sending(self.team.pk, "Bad rates", user_id=self.user.pk)
        create_notification.reset_mock()

        response = self.client.post(self._operation_url("unsuspend"))

        assert response.status_code == 302
        config = TeamWorkflowsConfig.objects.get(team_id=self.team.pk)
        assert config.email_sending_suspended_at is None
        assert config.email_sending_suspension_reason == ""
        unsuspended = ActivityLog.objects.get(scope="Team", team_id=self.team.id, activity="email_sending_unsuspended")
        assert unsuspended.user == self.user
        assert send_unsuspended.delay.call_args.kwargs["team_id"] == self.team.id
        create_notification.assert_called_once()

    @parameterized.expand(
        [
            ("suspend_without_reason", "suspend", {"reason": "   "}, False, 400, False),
            (
                "notification_fails_after_the_suspension",
                "suspend",
                {"reason": "Bounce rate above 10%"},
                True,
                302,
                True,
            ),
            ("operation_not_offered_in_this_state", "unsuspend", {}, False, 404, False),
        ]
    )
    @patch(f"{_SUSPENSION}.create_notification")
    @patch(f"{_SUSPENSION}.send_email_sending_suspended")
    def test_suspension_operations_refuse_or_keep_the_suspension(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        notification_fails: bool,
        expected_status: int,
        expect_suspended: bool,
        send_email: MagicMock,
        _create_notification: MagicMock,
    ) -> None:
        if notification_fails:
            send_email.delay.side_effect = RuntimeError("broker down")

        response = self.client.post(self._operation_url(operation_key), data)

        assert response.status_code == expected_status
        state = get_email_sending_state(self.team.pk)
        assert (state is not None and state.suspended_at is not None) == expect_suspended
