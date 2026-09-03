import json
from typing import TYPE_CHECKING, Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import Client

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.tasks.backend.logic.services import email_intake
from products.tasks.backend.logic.services.email_intake import EmailTaskIntake, InboundTaskEmail
from products.tasks.backend.models import Channel, Task, TeamTasksConfig

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

WORKFLOW = "products.tasks.backend.temporal.client.execute_task_processing_workflow"
QUOTA = "products.tasks.backend.logic.services.email_intake.is_team_limited"
EMAIL_AVAILABLE = "products.tasks.backend.logic.services.email_intake.is_email_available"
EMAIL_MESSAGE = "products.tasks.backend.logic.services.email_intake.EmailMessage"
INBOUND_DOMAIN = "products.tasks.backend.logic.services.email_intake.get_instance_setting"


def _inbound(**overrides: Any) -> InboundTaskEmail:
    fields: dict[str, Any] = {
        "message_id": "<abc@example.com>",
        "sender_email": "",
        "sender_name": "Alice",
        "subject": "Find out why signups dropped",
        "body": "Signups fell 30% last week. Check the funnel and tell me where.",
        "sender_authenticated": True,
    }
    fields.update(overrides)
    return InboundTaskEmail(**fields)


def _created_task(intake: EmailTaskIntake) -> Task:
    assert intake.outcome == "created" and intake.task_id is not None
    return Task.objects.get(id=intake.task_id)


@patch(EMAIL_AVAILABLE, return_value=False)
@patch(QUOTA, return_value=False)
@patch(WORKFLOW)
class TestStartTaskFromEmail(APIBaseTest):
    def test_creates_posthog_ai_style_task_in_personal_channel(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email))

        assert intake.outcome == "created"
        task = _created_task(intake)
        assert task.origin_product == Task.OriginProduct.EMAIL
        assert task.created_by_id == self.user.id
        assert task.title == "Find out why signups dropped"
        assert task.description.startswith("Signups fell 30%")
        assert task.repositories == []
        assert task.origin_key == "email:<abc@example.com>"
        assert task.channel is not None
        assert task.channel.system_role == Channel.SystemRole.PERSONAL
        assert task.channel.created_by_id == self.user.id
        run = task.runs.get()
        assert run.state["pending_dispatch"]["create_pr"] is False
        assert run.state["interaction_origin"] == "email"

    def test_sender_email_is_matched_case_insensitively(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email.upper()))

        assert intake.outcome == "created"
        assert _created_task(intake).created_by_id == self.user.id

    def test_same_message_id_yields_one_task(self, _workflow, _quota, _email):
        first = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email))
        second = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email))

        assert first.outcome == "created"
        assert second.outcome == "duplicate"
        assert second.task_id == first.task_id
        assert Task.objects.filter(origin_key="email:<abc@example.com>").count() == 1

    def test_unauthenticated_sender_is_refused(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(
            self.team, _inbound(sender_email=self.user.email, sender_authenticated=False)
        )

        assert intake.outcome == "unauthenticated"
        assert Task.objects.count() == 0

    def test_sender_outside_the_organization_is_refused(self, _workflow, _quota, _email):
        other_org = Organization.objects.create(name="Other")
        Team.objects.create(organization=other_org)
        outsider = User.objects.create_user(email="outsider@example.com", password=None, first_name="O")
        OrganizationMembership.objects.create(user=outsider, organization=other_org)

        intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=outsider.email))

        assert intake.outcome == "unknown_sender"
        assert Task.objects.count() == 0

    def test_subject_only_email_uses_subject_as_description(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email, body="  "))

        task = _created_task(intake)
        assert task.title == "Find out why signups dropped"
        assert task.description == "Find out why signups dropped"

    def test_reply_to_a_notification_keeps_the_quoted_report_and_drops_the_re_prefix(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(
            self.team,
            _inbound(
                sender_email=self.user.email,
                subject="Re: PostHog: Materialized view 'orders_daily' failed in Acme",
                body="Take a look at this failure and fix it if you can.",
                quoted_body="Take a look at this failure and fix it if you can.\n\n> orders_daily failed: Query exceeded timeout",
            ),
        )

        task = _created_task(intake)
        assert task.title == "PostHog: Materialized view 'orders_daily' failed in Acme"
        assert task.description.startswith("Take a look at this failure and fix it if you can.\n\nThe sender replied")
        assert task.description.endswith("> orders_daily failed: Query exceeded timeout")

    def test_auto_reply_creates_nothing(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(
            self.team, _inbound(sender_email=self.user.email, is_auto_reply=True)
        )

        assert intake == EmailTaskIntake(outcome="auto_reply")
        assert not Task.objects.filter(team=self.team).exists()

    def test_body_only_email_titles_from_first_line(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(
            self.team, _inbound(sender_email=self.user.email, subject="", body="First line\nsecond line")
        )

        task = _created_task(intake)
        assert task.title == "First line"
        assert task.description == "First line\nsecond line"

    def test_empty_email_creates_nothing(self, _workflow, _quota, _email):
        intake = email_intake.start_task_from_email(
            self.team, _inbound(sender_email=self.user.email, subject="", body="")
        )

        assert intake.outcome == "empty"
        assert Task.objects.count() == 0

    def test_quota_exceeded_creates_nothing(self, _workflow, quota, _email):
        quota.return_value = True

        intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email))

        assert intake.outcome == "quota_exceeded"
        assert Task.objects.count() == 0

    def test_acknowledgement_replies_in_the_senders_thread(self, _workflow, _quota, email_available):
        email_available.return_value = True
        with patch(EMAIL_MESSAGE) as message_cls:
            intake = email_intake.start_task_from_email(
                self.team, _inbound(sender_email=self.user.email, message_id="abc@example.com")
            )

        kwargs = message_cls.call_args.kwargs
        assert kwargs["headers"] == {
            "In-Reply-To": "<abc@example.com>",
            "References": "<abc@example.com>",
            "Auto-Submitted": "auto-replied",
        }
        assert kwargs["subject"] == "Started: Find out why signups dropped"
        assert kwargs["template_context"]["task_url"].endswith(f"/code/task/{intake.task_id}")
        message_cls.return_value.add_recipient.assert_called_once_with(email=self.user.email, name="Alice")
        message_cls.return_value.send.assert_called_once()

    def test_failed_acknowledgement_does_not_undo_the_task(self, _workflow, _quota, email_available):
        email_available.return_value = True
        with patch(EMAIL_MESSAGE, side_effect=RuntimeError("smtp down")):
            intake = email_intake.start_task_from_email(self.team, _inbound(sender_email=self.user.email))

        assert intake.outcome == "created"
        assert _created_task(intake) is not None


class TestInboxAddress(APIBaseTest):
    @parameterized.expand(
        [
            ("plain", "code-0123456789abcdef0123456789abcdef@inbound.example.com", "0123456789abcdef0123456789abcdef"),
            (
                "display_name",
                "Tasks <code-0123456789abcdef0123456789abcdef@inbound.example.com>",
                "0123456789abcdef0123456789abcdef",
            ),
            (
                "upper_case",
                "CODE-0123456789ABCDEF0123456789ABCDEF@inbound.example.com",
                "0123456789abcdef0123456789abcdef",
            ),
            ("support_address", "team-0123456789abcdef@inbound.example.com", None),
            ("short_token", "code-abc@inbound.example.com", None),
        ]
    )
    def test_extract_inbox_token(self, _name, recipient, expected):
        assert email_intake.extract_inbox_token(recipient) == expected

    @patch(INBOUND_DOMAIN, return_value="inbound.example.com")
    def test_ensure_rotate_and_clear(self, _setting):
        assert email_intake.get_inbox_address(self.team) is None

        first = email_intake.ensure_inbox_address(self.team)
        assert first is not None
        token = email_intake.extract_inbox_token(first)
        assert token is not None
        assert email_intake.find_team_by_inbox_token(token) == self.team
        assert email_intake.ensure_inbox_address(self.team) == first

        rotated = email_intake.ensure_inbox_address(self.team, rotate=True)
        assert rotated != first
        assert email_intake.find_team_by_inbox_token(token) is None

        email_intake.clear_inbox_address(self.team)
        assert email_intake.get_inbox_address(self.team) is None
        assert TeamTasksConfig.objects.get(team=self.team).email_inbound_token is None

    @patch(INBOUND_DOMAIN, return_value="")
    def test_no_inbound_domain_means_no_address(self, _setting):
        assert email_intake.ensure_inbox_address(self.team) is None
        assert not TeamTasksConfig.objects.filter(team=self.team, email_inbound_token__isnull=False).exists()


@patch(INBOUND_DOMAIN, return_value="inbound.example.com")
class TestEmailInboxConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_enable_rotate_disable_round_trip(self, _setting):
        url = f"/api/projects/{self.team.id}/tasks/config/email_inbox/"

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.json()["email_inbox_address"] is None

        response = self.client.post(url)
        assert response.status_code == 200
        address = response.json()["email_inbox_address"]
        assert address.endswith("@inbound.example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.json()["email_inbox_address"] == address

        response = self.client.post(url, {"rotate": True}, content_type="application/json")
        assert response.status_code == 200
        assert response.json()["email_inbox_address"] != address

        response = self.client.delete(url)
        assert response.status_code == 200
        assert response.json()["email_inbox_address"] is None

    def test_enable_without_inbound_domain_is_rejected(self, _setting):
        _setting.return_value = ""
        response = self.client.post(f"/api/projects/{self.team.id}/tasks/config/email_inbox/")
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"]

    def test_member_cannot_enable(self, _setting):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(f"/api/projects/{self.team.id}/tasks/config/email_inbox/")

        assert response.status_code == 403
        assert email_intake.get_inbox_address(self.team) is None


@patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
@patch(EMAIL_AVAILABLE, return_value=False)
@patch(QUOTA, return_value=False)
@patch(WORKFLOW)
class TestInboundWebhookRoutesToTasks(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.webhook = Client()
        with patch(INBOUND_DOMAIN, return_value="inbound.example.com"):
            self.address = email_intake.ensure_inbox_address(self.team)

    def _post(self, recipient: str, **overrides: str) -> "_MonkeyPatchedWSGIResponse":
        data = {
            "token": "t",
            "timestamp": "1",
            "signature": "s",
            "recipient": recipient,
            "from": f"Alice <{self.user.email}>",
            "sender": self.user.email,
            "X-Mailgun-Spf": "Pass",
            "Message-Id": "<hook@example.com>",
            "subject": "Rank the top errors",
            "stripped-text": "Which errors hurt the most users this week?",
            "body-plain": "Which errors hurt the most users this week?",
        }
        data.update(overrides)
        return self.webhook.post("/api/conversations/v1/email/inbound", data)

    def test_task_inbox_address_creates_a_task(self, _workflow, _quota, _email, _sig):
        assert self.address is not None
        response = self._post(self.address)

        assert response.status_code == 200
        task = Task.objects.get(origin_key="email:<hook@example.com>")
        assert task.origin_product == Task.OriginProduct.EMAIL
        assert task.created_by_id == self.user.id
        assert task.title == "Rank the top errors"

    def test_reply_to_a_failure_email_carries_the_quoted_report(self, _workflow, _quota, _email, _sig):
        assert self.address is not None
        response = self._post(
            self.address,
            subject="Re: PostHog: Materialized view 'orders_daily' failed in Acme",
            **{
                "stripped-text": "Take a look at this failure and fix it if you can.",
                "body-plain": "Take a look at this failure and fix it if you can.\n\n> orders_daily: Query exceeded timeout",
            },
        )

        assert response.status_code == 200
        task = Task.objects.get(origin_key="email:<hook@example.com>")
        assert task.title == "PostHog: Materialized view 'orders_daily' failed in Acme"
        assert "Query exceeded timeout" in task.description

    def test_out_of_office_reply_creates_nothing(self, _workflow, _quota, _email, _sig):
        assert self.address is not None
        response = self._post(
            self.address, **{"message-headers": json.dumps([["Auto-Submitted", "auto-replied"], ["Subject", "x"]])}
        )

        assert response.status_code == 200
        assert Task.objects.count() == 0

    def test_unknown_inbox_token_is_not_found(self, _workflow, _quota, _email, _sig):
        with patch("products.conversations.backend.api.email_events.is_primary_region", return_value=False):
            response = self._post("code-ffffffffffffffffffffffffffffffff@inbound.example.com")

        assert response.status_code == 404
        assert Task.objects.count() == 0

    def test_spoofed_sender_creates_nothing(self, _workflow, _quota, _email, _sig):
        assert self.address is not None
        response = self._post(self.address, sender="attacker@evil.com")

        assert response.status_code == 200
        assert Task.objects.count() == 0
