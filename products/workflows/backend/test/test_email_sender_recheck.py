from unittest.mock import patch

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.team import Team

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.tasks.email_sender_verification import recheck_pending_email_senders
from products.workflows.backend.test.email_domain_api_test_case import ALL_KINDS, DOMAIN, EmailDomainApiTestCase


class TestPendingEmailSenderRecheck(EmailDomainApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("products.workflows.backend.tasks.email_sender_verification.time.sleep"))

    def test_verifies_senders_whose_records_were_published_after_the_owner_left(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        sibling = self.create_sender(f"news@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)

        recheck_pending_email_senders()

        assert self.is_verified(sender) and self.is_verified(sibling)
        assert TeamWorkflowsConfig.objects.get(team_id=self.team.id).default_email_integration_id == sender

    def test_a_sender_that_fails_to_verify_does_not_stop_the_others(self) -> None:
        broken = Integration.objects.create(
            team=self.team,
            kind="email",
            config={
                "email": "hi@bad_domain.example.com",
                "domain": "bad_domain.example.com",
                "provider": "ses",
                "verified": False,
            },
        )
        self.world.dns.publish("feedback.bad_domain.example.com", "MX", "10 feedback-smtp.us-east-1.amazonses.com.")
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)

        recheck_pending_email_senders()

        assert not self.is_verified(broken.id)
        assert self.is_verified(sender)

    def test_verifies_a_sender_whose_domain_another_project_moved_to_its_own_mail_from_subdomain(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        waiting = self.create_sender(f"hello@{DOMAIN}", team=other_team)
        sender = self.create_sender(f"hello@{DOMAIN}")
        config = Integration.objects.get(id=sender).config
        changed = self.client.patch(
            f"/api/projects/{self.team.id}/integrations/{sender}/email",
            {"config": {**config, "mail_from_subdomain": "bounce"}},
            format="json",
        )
        assert changed.status_code == status.HTTP_200_OK, changed.json()
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        assert self.verify(sender).status_code == status.HTTP_200_OK

        recheck_pending_email_senders()

        assert self.is_verified(waiting)

    def test_leaves_ses_alone_for_senders_whose_mail_from_record_is_not_at_ses(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *(kind for kind in ALL_KINDS if kind != "mail_from_mx"))
        writes_before = list(self.world.ses.writes)

        recheck_pending_email_senders()

        assert self.world.ses.writes == writes_before
        assert not self.is_verified(sender)
