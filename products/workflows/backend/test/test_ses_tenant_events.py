import json
import base64
import datetime
from typing import Any, cast

from unittest.mock import patch

from django.core.cache import cache
from django.http.response import HttpResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

import requests
import structlog.testing
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from parameterized import parameterized

from posthog.ingress.contracts import WebhookDelivery

from products.workflows.backend.facade.api import accept_ses_event

TOPIC = "arn:aws:sns:us-east-1:123456789012:ses-tenant-events"
WEBHOOK_PATH = "/webhooks/workflows/ses-events"
SUBSCRIBE_URL = "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&Token=tok"
_CERT_URL = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-01d088a6f77103d0fe307c0069e40ed6.pem"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_SUBJECT = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
_CERT_PEM = (
    x509.CertificateBuilder()
    .subject_name(_SUBJECT)
    .issuer_name(_SUBJECT)
    .public_key(_KEY.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2020, 1, 1))
    .not_valid_after(datetime.datetime(2040, 1, 1))
    .sign(_KEY, hashes.SHA256())
    .public_bytes(serialization.Encoding.PEM)
)
_SIGNED_KEYS = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
    "SubscriptionConfirmation": ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"),
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


def _notification(event: dict[str, Any], *, message_id: str = "mid-1", topic: str = TOPIC) -> dict[str, Any]:
    return {
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": topic,
        "Message": json.dumps(event),
        "Timestamp": "2026-07-30T00:00:00.000Z",
    }


def _subscription_confirmation(*, message_id: str = "mid-2", subscribe_url: str = SUBSCRIBE_URL) -> dict[str, Any]:
    return {
        "Type": "SubscriptionConfirmation",
        "MessageId": message_id,
        "TopicArn": TOPIC,
        "Token": "tok",
        "Message": "You have chosen to subscribe...",
        "SubscribeURL": subscribe_url,
        "Timestamp": "2026-07-30T00:00:00.000Z",
    }


def _signed(message: dict[str, Any]) -> dict[str, Any]:
    """The message as AWS would send it: signature version 2 over the canonical string-to-sign."""
    signed = {**message, "SignatureVersion": "2", "SigningCertURL": _CERT_URL}
    string_to_sign = "".join(f"{key}\n{signed[key]}\n" for key in _SIGNED_KEYS[signed["Type"]] if key in signed)
    signature = _KEY.sign(string_to_sign.encode(), padding.PKCS1v15(), hashes.SHA256())
    signed["Signature"] = base64.b64encode(signature).decode()
    return signed


def _delivery(message: dict[str, Any]) -> WebhookDelivery:
    return WebhookDelivery(
        provider="sns",
        app="default",
        delivery_id=str(message["MessageId"]),
        event_type=str(message["Type"]),
        payload=message,
        received_at=timezone.now(),
        context={"topic_arn": TOPIC},
    )


class TestAcceptSesEvent(SimpleTestCase):
    def setUp(self) -> None:
        sync = patch("products.workflows.backend.services.ses_tenant_events.sync_ses_tenant_state_task")
        self.sync_mock = sync.start()
        self.addCleanup(sync.stop)

    def test_enqueues_a_sync_for_the_tenant_named_in_the_event(self) -> None:
        accept_ses_event(_delivery(_notification(_eventbridge_event())))

        self.sync_mock.delay.assert_called_once_with(42)

    def test_finds_the_tenant_in_resource_arns_when_detail_has_no_name(self) -> None:
        event = _eventbridge_event(detail={}, resources=["arn:aws:ses:us-east-1:123456789012:tenant/team-7/deadbeef"])

        accept_ses_event(_delivery(_notification(event)))

        self.sync_mock.delay.assert_called_once_with(7)

    def test_ignores_events_from_other_sources(self) -> None:
        accept_ses_event(_delivery(_notification(_eventbridge_event(source="aws.health"))))

        assert not self.sync_mock.delay.called

    def test_confirms_subscriptions_by_fetching_the_subscribe_url(self) -> None:
        with patch("products.workflows.backend.services.ses_tenant_events.requests.get") as get_mock:
            accept_ses_event(_delivery(_subscription_confirmation()))

        get_mock.assert_called_once_with(SUBSCRIBE_URL, timeout=5)

    @parameterized.expand(
        [
            ("off_aws", "https://attacker.example.com/confirm"),
            ("not_a_url", "not-a-url"),
        ]
    )
    def test_refuses_a_malformed_subscribe_url_without_raising(self, _name: str, subscribe_url: str) -> None:
        # Raising would cost the delivery its receipt and make SNS redeliver a handshake that can
        # never be confirmed.
        message = _subscription_confirmation(subscribe_url=subscribe_url)

        with patch("products.workflows.backend.services.ses_tenant_events.requests.get") as get_mock:
            accept_ses_event(_delivery(message))

        assert not get_mock.called

    def test_a_failed_confirmation_callback_is_raised_rather_than_swallowed(self) -> None:
        with patch(
            "products.workflows.backend.services.ses_tenant_events.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            with self.assertRaises(requests.RequestException):
                accept_ses_event(_delivery(_subscription_confirmation()))


@override_settings(WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS=[TOPIC])
class TestSesTenantEventsEndpoint(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        # The dedup mark outlives a test, so a shared one would make the second delivery a no-op.
        cache.clear()
        cert = patch("posthog.ingress.verify.sns_signature._fetch_signing_cert", return_value=_CERT_PEM)
        cert.start()
        self.addCleanup(cert.stop)
        sync = patch("products.workflows.backend.services.ses_tenant_events.sync_ses_tenant_state_task")
        self.sync_mock = sync.start()
        self.addCleanup(sync.stop)

    def _post(self, payload: dict[str, Any]) -> HttpResponse:
        return cast(HttpResponse, self.client.post(WEBHOOK_PATH, data=json.dumps(payload), content_type="text/plain"))

    def test_enqueues_a_sync_for_the_tenant_named_in_a_verified_event(self) -> None:
        response = self._post(_signed(_notification(_eventbridge_event())))

        assert response.status_code == 202
        self.sync_mock.delay.assert_called_once_with(42)

    def test_rejects_messages_from_unknown_topics(self) -> None:
        message = _signed(_notification(_eventbridge_event(), topic="arn:aws:sns:us-east-1:999:other"))

        response = self._post(message)

        assert response.status_code == 403
        assert not self.sync_mock.delay.called

    def test_rejects_messages_with_invalid_signatures(self) -> None:
        tampered = {**_signed(_notification(_eventbridge_event())), "Message": json.dumps(_eventbridge_event())[:-1]}

        response = self._post(tampered)

        assert response.status_code == 403
        assert not self.sync_mock.delay.called

    @override_settings(WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS=[])
    def test_is_inert_when_no_topic_is_allowlisted(self) -> None:
        with structlog.testing.capture_logs() as logs:
            response = self._post(_signed(_notification(_eventbridge_event())))

        assert response.status_code == 404
        assert response.content == b""
        assert not self.sync_mock.delay.called
        unconfigured = next(log for log in logs if log["event"] == "ingress_webhook_not_configured")
        assert unconfigured["log_level"] == "warning"

    @parameterized.expand(
        [
            ("callback_succeeds", SUBSCRIBE_URL, None, 202, True),
            ("callback_fails", SUBSCRIBE_URL, requests.RequestException("boom"), 502, True),
            # Terminal, so SNS stops: a redelivery would carry the same unusable URL.
            ("subscribe_url_is_not_aws", "https://attacker.example.com/confirm", None, 202, False),
        ]
    )
    def test_confirms_a_verified_subscription(
        self,
        _name: str,
        subscribe_url: str,
        callback_error: Exception | None,
        expected_status: int,
        expect_callback: bool,
    ) -> None:
        with patch(
            "products.workflows.backend.services.ses_tenant_events.requests.get", side_effect=callback_error
        ) as get_mock:
            response = self._post(_signed(_subscription_confirmation(subscribe_url=subscribe_url)))

        assert response.status_code == expected_status
        if expect_callback:
            get_mock.assert_called_once_with(subscribe_url, timeout=5)
        else:
            assert not get_mock.called
