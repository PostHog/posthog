from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from django.core import mail

import posthoganalytics
from parameterized import parameterized
from rest_framework import status

from posthog.models.instance_setting import override_instance_config
from posthog.models.user import User
from posthog.tasks.email import send_email_sender_domain_sending_stopped

from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.workflows.backend.services.ses_sender_health import SES_SENDER_HEALTH_FLAG
from products.workflows.backend.tasks.ses_sender_health import check_ses_sender_health
from products.workflows.backend.test.email_domain_api_test_case import ALL_KINDS, DOMAIN, EmailDomainApiTestCase

OTHER_DOMAIN = "news.example.com"
PENDING_DOMAIN = "pending.example.com"


class TestSesSenderHealth(EmailDomainApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.rolled_out: bool | None = True
        flag_client = posthoganalytics.feature_enabled

        def feature_enabled(key: str, *args: Any, **kwargs: Any) -> bool | None:
            return self.rolled_out if key == SES_SENDER_HEALTH_FLAG else flag_client(key, *args, **kwargs)

        self.enterContext(patch("posthoganalytics.feature_enabled", side_effect=feature_enabled))

    def deliver_notices(self) -> None:
        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))
        self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key != SES_SENDER_HEALTH_FLAG or self.rolled_out,
            )
        )

    def verified_sender(self, email: str) -> int:
        sender = self.create_sender(email)
        self.publish(self.records_to_publish(sender, domain=email.split("@")[1]), *ALL_KINDS)
        assert self.verify(sender).status_code == status.HTTP_200_OK
        return sender

    def sender_config(self, integration_id: int) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/integrations/{integration_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["config"]

    def sending_stopped(self, integration_id: int) -> bool:
        return self.sender_config(integration_id).get("ses_sending_status") == "failed"

    def test_marks_the_verified_senders_of_a_domain_ses_stopped_and_keeps_them_verified(self) -> None:
        sender = self.verified_sender(f"hello@{DOMAIN}")
        sibling = self.verified_sender(f"news@{DOMAIN}")
        healthy = self.verified_sender(f"hello@{OTHER_DOMAIN}")
        pending = self.create_sender(f"hello@{PENDING_DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        self.world.ses.identities[PENDING_DOMAIN].forced_verification_status = "Failed"

        check_ses_sender_health()

        assert self.sending_stopped(sender) and self.sending_stopped(sibling)
        assert self.sender_config(sender)["verified"] is True
        assert not self.sending_stopped(healthy)
        assert not self.sending_stopped(pending)

    @parameterized.expand(
        [
            ("on_the_next_check", lambda test, sender: check_ses_sender_health()),
            ("when_someone_verifies_the_sender", lambda test, sender: test.verify(sender)),
        ]
    )
    def test_clears_the_warning_once_ses_accepts_the_domain_again(
        self, _name: str, recover: Callable[["TestSesSenderHealth", int], object]
    ) -> None:
        sender = self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        check_ses_sender_health()
        assert self.sending_stopped(sender)
        self.world.ses.identities[DOMAIN].forced_verification_status = None

        recover(self, sender)

        assert not self.sending_stopped(sender)

    @parameterized.expand(
        [
            ("switching_the_rollout_off_clears_it", False, False),
            ("a_flag_evaluation_outage_keeps_it", None, True),
        ]
    )
    def test_the_rollout_decides_whether_a_warning_stays(
        self, _name: str, rollout: bool | None, still_stopped: bool
    ) -> None:
        sender = self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        check_ses_sender_health()
        assert self.sending_stopped(sender)
        self.rolled_out = rollout

        check_ses_sender_health()

        assert self.sending_stopped(sender) is still_stopped

    def test_tells_the_project_admins_once_when_a_domain_in_the_rollout_stops_sending(self) -> None:
        self.deliver_notices()
        User.objects.create_and_join(self.organization, "member@example.com", None)
        self.verified_sender(f"hello@{DOMAIN}")
        self.verified_sender(f"news@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        mail.outbox.clear()
        self.rolled_out = False
        check_ses_sender_health()
        assert mail.outbox == []
        self.rolled_out = True

        check_ses_sender_health()
        check_ses_sender_health()

        [message] = mail.outbox
        assert message.to == [self.user.email]
        assert DOMAIN in message.subject
        [notification] = stored_notifications_for_team(self.team.id)
        assert DOMAIN in notification.body
        assert notification.source_url == f"/project/{self.team.id}/workflows/channels"

    @parameterized.expand(
        [
            ("the_broker_refuses_it", False),
            ("the_broker_takes_it_but_the_publish_still_fails", True),
        ]
    )
    def test_tells_the_admins_once_when_queueing_the_email_fails(self, _name: str, broker_took_it: bool) -> None:
        self.deliver_notices()
        sender = self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        mail.outbox.clear()
        queue_email = send_email_sender_domain_sending_stopped.delay

        def failing_publish(*args: Any, **kwargs: Any) -> None:
            if broker_took_it:
                queue_email(*args, **kwargs)
            raise ConnectionError

        with patch.object(send_email_sender_domain_sending_stopped, "delay", side_effect=failing_publish):
            check_ses_sender_health()
        assert stored_notifications_for_team(self.team.id) == []

        check_ses_sender_health()

        assert self.sending_stopped(sender)
        assert len(mail.outbox) == 1
        assert len(stored_notifications_for_team(self.team.id)) == 1
