import json
from typing import Any

from unittest.mock import patch

from django.http.response import HttpResponseBase
from django.test import Client, TestCase, override_settings

TOPIC = "arn:aws:sns:us-east-1:123456789012:ses-tenant-events"
WEBHOOK_PATH = "/webhooks/workflows/ses-events"


def _sns_notification(event: dict[str, Any], topic: str = TOPIC) -> dict[str, Any]:
    return {
        "Type": "Notification",
        "MessageId": "mid-1",
        "TopicArn": topic,
        "Message": json.dumps(event),
        "Timestamp": "2026-07-30T00:00:00.000Z",
        "SignatureVersion": "1",
        "Signature": "sig",
        "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
    }


def _eventbridge_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "version": "0",
        "source": "aws.ses",
        "detail-type": "Sending Status Disabled",
        "resources": [],
        "detail": {"tenantName": "team-42"},
    }
    event.update(overrides)
    return event


@override_settings(WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS=[TOPIC])
class TestSesTenantEventsWebhook(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        verify = patch("products.workflows.backend.api.ses_events_webhook.verify_sns_message", return_value=True)
        self.verify_mock = verify.start()
        self.addCleanup(verify.stop)
        sync = patch("products.workflows.backend.api.ses_events_webhook.sync_ses_tenant_state_task")
        self.sync_mock = sync.start()
        self.addCleanup(sync.stop)

    def _post(self, payload: dict[str, Any]) -> HttpResponseBase:
        return self.client.post(WEBHOOK_PATH, data=json.dumps(payload), content_type="text/plain")

    def test_enqueues_a_sync_for_the_tenant_named_in_the_event(self) -> None:
        response = self._post(_sns_notification(_eventbridge_event()))

        assert response.status_code == 202
        self.sync_mock.delay.assert_called_once_with(42)

    def test_finds_the_tenant_in_resource_arns_when_detail_has_no_name(self) -> None:
        event = _eventbridge_event(detail={}, resources=["arn:aws:ses:us-east-1:123456789012:tenant/team-7/deadbeef"])

        response = self._post(_sns_notification(event))

        assert response.status_code == 202
        self.sync_mock.delay.assert_called_once_with(7)

    def test_acks_but_ignores_events_from_other_sources(self) -> None:
        response = self._post(_sns_notification(_eventbridge_event(source="aws.health")))

        assert response.status_code == 200
        assert not self.sync_mock.delay.called

    def test_rejects_messages_from_unknown_topics(self) -> None:
        response = self._post(_sns_notification(_eventbridge_event(), topic="arn:aws:sns:us-east-1:999:other"))

        assert response.status_code == 403
        assert not self.sync_mock.delay.called

    def test_rejects_messages_with_invalid_signatures(self) -> None:
        self.verify_mock.return_value = False

        response = self._post(_sns_notification(_eventbridge_event()))

        assert response.status_code == 403
        assert not self.sync_mock.delay.called

    @override_settings(WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS=[])
    def test_is_inert_when_no_topic_is_allowlisted(self) -> None:
        response = self._post(_sns_notification(_eventbridge_event()))

        assert response.status_code == 404
        assert not self.sync_mock.delay.called

    def test_confirms_subscriptions_by_fetching_the_subscribe_url(self) -> None:
        subscribe_url = "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&Token=tok"
        payload = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "mid-2",
            "TopicArn": TOPIC,
            "Token": "tok",
            "Message": "You have chosen to subscribe...",
            "SubscribeURL": subscribe_url,
            "Timestamp": "2026-07-30T00:00:00.000Z",
            "SignatureVersion": "1",
            "Signature": "sig",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }

        with patch("products.workflows.backend.api.ses_events_webhook.requests.get") as get_mock:
            response = self._post(payload)

        assert response.status_code == 200
        get_mock.assert_called_once_with(subscribe_url, timeout=5)

    def test_rejects_subscription_confirmations_pointing_off_aws(self) -> None:
        payload = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "mid-3",
            "TopicArn": TOPIC,
            "Token": "tok",
            "Message": "...",
            "SubscribeURL": "https://attacker.example.com/confirm",
            "Timestamp": "2026-07-30T00:00:00.000Z",
            "SignatureVersion": "1",
            "Signature": "sig",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }

        with patch("products.workflows.backend.api.ses_events_webhook.requests.get") as get_mock:
            response = self._post(payload)

        assert response.status_code == 400
        assert not get_mock.called
