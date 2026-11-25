from typing import Any

from unittest.mock import patch

from django.core import mail
from django.core.mail import EmailMultiAlternatives

from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.workflow_email_senders import SENDER_UNUSABLE_NOTICE_FLAG
from products.workflows.backend.tasks.workflow_email_health import notify_unusable_workflow_email_senders
from products.workflows.backend.test.email_domain_api_test_case import DOMAIN, EmailDomainApiTestCase


def email_step(step_id: str, name: str, sender_id: int) -> dict[str, Any]:
    return {
        "id": step_id,
        "name": name,
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {"email": {"value": {"from": {"integrationId": sender_id}}}},
        },
    }


class TestWorkflowEmailSenderNotices(EmailDomainApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.rolled_out: bool | None = True
        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))
        self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key != SENDER_UNUSABLE_NOTICE_FLAG or self.rolled_out,
            )
        )
        self.verified = self.verified_sender(f"hello@{DOMAIN}")
        self.unverified = self.create_sender(f"news@{DOMAIN}")
        self.deleted = self.create_sender(f"old@{DOMAIN}")
        assert self.client.delete(f"/api/projects/{self.team.id}/integrations/{self.deleted}").status_code == 204
        mail.outbox.clear()

    def workflow(
        self, name: str, *steps: dict[str, Any], state: str = HogFlow.State.ACTIVE, creator: User | None = None
    ) -> HogFlow:
        trigger = {"id": "trigger_node", "type": "trigger", "config": {"type": "event", "filters": {}}}
        return HogFlow.objects.create(
            team=self.team, name=name, status=state, actions=[trigger, *steps], created_by=creator or self.user
        )

    def test_emails_the_admins_once_about_live_workflow_steps_whose_sender_cannot_send(self) -> None:
        broken = self.workflow(
            "Onboarding",
            email_step("welcome", "Welcome email", self.deleted),
            email_step("tips", "Tips email", self.unverified),
            email_step("hello", "Hello email", self.verified),
        )
        self.workflow("Healthy", email_step("hello", "Hello email", self.verified))
        self.workflow("Draft", email_step("welcome", "Welcome email", self.deleted), state=HogFlow.State.DRAFT)
        self.workflow("Archived", email_step("welcome", "Welcome email", self.deleted), state=HogFlow.State.ARCHIVED)

        notify_unusable_workflow_email_senders()
        notify_unusable_workflow_email_senders()

        [message] = mail.outbox
        assert message.to == [self.user.email]
        assert "Onboarding" in message.subject
        assert isinstance(message, EmailMultiAlternatives)
        body = str(message.alternatives[0][0])
        assert "Welcome email" in body and "Tips email" in body
        assert "Hello email" not in body
        assert f"/project/{self.team.id}/workflows/{broken.id}/workflow" in body

    def test_emails_again_when_the_steps_senders_break_differently(self) -> None:
        flow = self.workflow("Onboarding", email_step("welcome", "Welcome email", self.deleted))
        notify_unusable_workflow_email_senders()
        flow.actions = [flow.actions[0], email_step("welcome", "Welcome email", self.unverified)]
        flow.save()

        notify_unusable_workflow_email_senders()

        assert len(mail.outbox) == 2

    @parameterized.expand(
        [
            ("held_back", False, 1, 0),
            ("undecided", None, 0, 1),
        ]
    )
    def test_projects_outside_the_rollout_are_only_logged(
        self, _name: str, rollout: bool | None, held_back: int, undecided: int
    ) -> None:
        self.rolled_out = rollout
        flow = self.workflow("Onboarding", email_step("welcome", "Welcome email", self.deleted))

        with capture_logs() as logs:
            notify_unusable_workflow_email_senders()

        assert mail.outbox == []
        [summary] = [log for log in logs if log["event"] == "workflow_email_sender_unusable_shadow"]
        assert summary["undecided"] == undecided
        expected = [{"team_id": self.team.id, "workflow_id": str(flow.id), "sender_ids": [str(self.deleted)]}]
        assert summary["held_back"] == expected[:held_back]

    @parameterized.expand([("still_a_member", True), ("left_the_organization", False)])
    def test_includes_the_workflow_creator_while_they_can_open_the_project(self, _name: str, member: bool) -> None:
        creator = User.objects.create_and_join(self.organization, "creator@example.com", None)
        if not member:
            OrganizationMembership.objects.filter(user=creator).delete()
        self.workflow("Onboarding", email_step("welcome", "Welcome email", self.deleted), creator=creator)

        notify_unusable_workflow_email_senders()

        recipients = sorted(address for message in mail.outbox for address in message.to)
        assert recipients == sorted([self.user.email, *(["creator@example.com"] if member else [])])
