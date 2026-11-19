import json
from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from django.core import mail
from django.db import OperationalError

import responses
import posthoganalytics
from botocore.exceptions import ClientError
from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.integrations import IntegrationManager, IntegrationPatch
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration.email import SES_SENDING_STATUS_KEY
from posthog.models.user import User
from posthog.tasks.email import send_email_sender_domain_sending_stopped

from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.workflows.backend.services.ses_sender_health import SES_SENDER_HEALTH_FLAG
from products.workflows.backend.tasks.ses_sender_health import check_ses_sender_health
from products.workflows.backend.test.email_domain_api_test_case import ALL_KINDS, DOMAIN, EmailDomainApiTestCase
from products.workflows.backend.tests.fakes.faults import AwsFault

OTHER_DOMAIN = "news.example.com"
PENDING_DOMAIN = "pending.example.com"
ERROR_TRACKING_HOST = "https://error-tracking.example.com"


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

    def test_tells_the_admins_again_when_the_domain_stops_again_after_recovering(self) -> None:
        self.deliver_notices()
        self.verified_sender(f"hello@{DOMAIN}")
        mail.outbox.clear()
        for ses_status in ("Failed", None, "Failed"):
            self.world.ses.identities[DOMAIN].forced_verification_status = ses_status
            check_ses_sender_health()

        assert len(mail.outbox) == 2
        assert len(stored_notifications_for_team(self.team.id)) == 2

    def test_tells_the_admins_once_when_two_checks_overlap(self) -> None:
        self.deliver_notices()
        self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        mail.outbox.clear()
        queue_email = send_email_sender_domain_sending_stopped.delay
        checks_started = 0

        def publish_during_another_check(*args: Any, **kwargs: Any) -> None:
            nonlocal checks_started
            checks_started += 1
            if checks_started == 1:
                check_ses_sender_health()
            queue_email(*args, **kwargs)

        with patch.object(send_email_sender_domain_sending_stopped, "delay", side_effect=publish_during_another_check):
            check_ses_sender_health()

        assert len(mail.outbox) == 1
        assert len(stored_notifications_for_team(self.team.id)) == 1

    def test_tells_the_admins_on_the_next_check_when_saving_the_stop_fails(self) -> None:
        self.deliver_notices()
        sender = self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        mail.outbox.clear()
        credentials = IntegrationManager.email.credentials
        write = credentials.update_where

        def fail_every_write_after_the_mark(team_id: int, *, where: Any, patch: IntegrationPatch) -> Any:
            if patch.config_patch and SES_SENDING_STATUS_KEY not in patch.config_patch:
                raise OperationalError
            return write(team_id, where=where, patch=patch)

        with patch.object(credentials, "update_where", side_effect=fail_every_write_after_the_mark):
            with self.assertRaises(OperationalError):
                check_ses_sender_health()
        check_ses_sender_health()

        assert self.sending_stopped(sender)
        assert len(mail.outbox) == 1

    def test_creates_the_notification_on_the_next_check_when_creating_it_fails(self) -> None:
        self.deliver_notices()
        self.verified_sender(f"hello@{DOMAIN}")
        self.world.ses.identities[DOMAIN].forced_verification_status = "Failed"
        mail.outbox.clear()

        with patch(
            "products.workflows.backend.services.ses_sender_health.create_notification", side_effect=OperationalError
        ):
            check_ses_sender_health()
        assert stored_notifications_for_team(self.team.id) == []
        check_ses_sender_health()

        assert len(mail.outbox) == 1
        assert len(stored_notifications_for_team(self.team.id)) == 1

    def test_keeps_a_newer_stop_pending_when_an_older_check_finishes_late(self) -> None:
        self.deliver_notices()
        self.verified_sender(f"hello@{DOMAIN}")
        identity = self.world.ses.identities[DOMAIN]
        identity.forced_verification_status = "Failed"
        mail.outbox.clear()
        queue_email = send_email_sender_domain_sending_stopped.delay
        publishes = 0

        def recover_and_stop_again_while_publishing(*args: Any, **kwargs: Any) -> None:
            nonlocal publishes
            publishes += 1
            if publishes == 2:
                raise ConnectionError
            identity.forced_verification_status = None
            check_ses_sender_health()
            identity.forced_verification_status = "Failed"
            check_ses_sender_health()
            queue_email(*args, **kwargs)

        with patch.object(
            send_email_sender_domain_sending_stopped, "delay", side_effect=recover_and_stop_again_while_publishing
        ):
            check_ses_sender_health()
        check_ses_sender_health()

        assert len(mail.outbox) == 2

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

    @responses.activate
    def test_reports_why_ses_refused_the_identity_list_and_still_fails_the_run(self) -> None:
        responses.post(f"{ERROR_TRACKING_HOST}/batch/", json={"status": 1})
        self.world.faults.inject("sesv2.list_email_identities", AwsFault.ACCESS_DENIED)

        with (
            patch.object(posthoganalytics, "api_key", "phc_test"),
            patch.object(posthoganalytics, "disabled", False),
            patch.object(
                posthoganalytics,
                "default_client",
                posthoganalytics.Client("phc_test", host=ERROR_TRACKING_HOST, sync_mode=True),
            ),
            capture_logs() as logs,
            self.assertRaises(ClientError),
        ):
            check_ses_sender_health()

        [delivery] = responses.calls
        [event] = json.loads(delivery.request.body)["batch"]
        assert event["event"] == "$exception"
        assert event["properties"]["error_code"] == "AccessDenied"
        assert [log["error_code"] for log in logs if "error_code" in log] == ["AccessDenied"]
