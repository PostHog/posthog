import base64
import datetime
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from parameterized import parameterized

from products.workflows.backend.services.sns_verification import (
    _MAX_UNKNOWN_CERT_FETCHES_PER_MINUTE,
    _fetch_signing_cert,
    is_valid_sns_cert_url,
    is_valid_sns_url,
    remember_verified_cert_url,
    verify_sns_message,
)

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


def _signed_notification(tamper: dict[str, Any] | None = None) -> dict[str, Any]:
    message = {
        "Type": "Notification",
        "MessageId": "mid-1",
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:topic",
        "Message": '{"source":"aws.ses"}',
        "Timestamp": "2026-07-30T00:00:00.000Z",
        "SignatureVersion": "2",
        "SigningCertURL": _CERT_URL,
    }
    string_to_sign = "".join(
        f"{key}\n{message[key]}\n" for key in ["Message", "MessageId", "Timestamp", "TopicArn", "Type"]
    )
    signature = _KEY.sign(string_to_sign.encode(), padding.PKCS1v15(), hashes.SHA256())
    message["Signature"] = base64.b64encode(signature).decode()
    message.update(tamper or {})
    return message


class TestSnsVerification(TestCase):
    def _verify(self, message: dict[str, Any]) -> bool:
        with patch("products.workflows.backend.services.sns_verification._fetch_signing_cert", return_value=_CERT_PEM):
            return verify_sns_message(message)

    def test_accepts_a_correctly_signed_notification(self) -> None:
        assert self._verify(_signed_notification()) is True

    @parameterized.expand(
        [
            ("tampered_message", {"Message": '{"source":"aws.ses","evil":true}'}),
            ("tampered_topic", {"TopicArn": "arn:aws:sns:us-east-1:666:other"}),
            ("garbage_signature", {"Signature": base64.b64encode(b"nope").decode()}),
            ("cert_not_from_sns", {"SigningCertURL": "https://attacker.example.com/cert.pem"}),
            ("cert_over_http", {"SigningCertURL": f"http{_CERT_URL[5:]}"}),
            # Right host, but not a path SNS serves a certificate from.
            ("cert_path_not_a_cert", {"SigningCertURL": "https://sns.us-east-1.amazonaws.com/evil.pem"}),
            ("unknown_type", {"Type": "SomethingElse"}),
            # SignatureVersion 1 is SHA1-signed and rejected outright; the topic must be
            # configured with SignatureVersion=2
            ("sha1_signature_version", {"SignatureVersion": "1"}),
        ]
    )
    def test_rejects(self, _name: str, tamper: dict[str, Any]) -> None:
        assert self._verify(_signed_notification(tamper)) is False

    @parameterized.expand(
        [
            ("sns_regional", "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService.pem", True),
            ("subdomain_spoof", "https://sns.us-east-1.amazonaws.com.evil.com/cert.pem", False),
            ("wrong_service", "https://s3.us-east-1.amazonaws.com/cert.pem", False),
            # An SNS host on a port SNS does not serve: the fetch would just hang out the timeout.
            ("dead_port", "https://sns.us-east-1.amazonaws.com:81/SimpleNotificationService-abcdef1234.pem", False),
            ("explicit_443", "https://sns.us-east-1.amazonaws.com:443/SimpleNotificationService-abcdef1234.pem", True),
            ("non_numeric_port", "https://sns.us-east-1.amazonaws.com:port/cert.pem", False),
            ("empty", "", False),
            ("none", None, False),
        ]
    )
    def test_url_validation(self, _name: str, url: str | None, expected: bool) -> None:
        assert is_valid_sns_url(url) is expected

    @parameterized.expand(
        [
            ("real_cert_path", _CERT_URL, True),
            ("arbitrary_path", "https://sns.us-east-1.amazonaws.com/evil.pem", False),
            # The subscribe URL is a different shape and must not pass as a cert URL.
            ("subscribe_url", "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription", False),
        ]
    )
    def test_cert_url_validation(self, _name: str, url: str, expected: bool) -> None:
        assert is_valid_sns_cert_url(url) is expected


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestSigningCertFetch(SimpleTestCase):
    """An unauthenticated caller who learns the topic ARN reaches the fetch, so it stays cheap."""

    def setUp(self) -> None:
        cache.clear()

    def test_a_cert_url_sns_could_not_serve_is_rejected_without_fetching(self) -> None:
        message = _signed_notification({"SigningCertURL": "https://sns.us-east-1.amazonaws.com/evil.pem"})

        with patch("products.workflows.backend.services.sns_verification.requests.get") as get:
            assert verify_sns_message(message) is False

        assert get.call_count == 0

    def test_a_failed_fetch_is_not_retried_for_the_same_url(self) -> None:
        with patch(
            "products.workflows.backend.services.sns_verification.requests.get",
            side_effect=requests.RequestException("boom"),
        ) as get:
            assert _fetch_signing_cert(_CERT_URL) is None
            assert _fetch_signing_cert(_CERT_URL) is None

        assert get.call_count == 1

    def _spend_the_budget(self) -> None:
        with patch("products.workflows.backend.services.sns_verification.requests.get") as get:
            get.return_value.content = _CERT_PEM
            for index in range(_MAX_UNKNOWN_CERT_FETCHES_PER_MINUTE):
                _fetch_signing_cert(f"https://sns.us-east-1.amazonaws.com/SimpleNotificationService-{index:032x}.pem")

    def test_fetching_a_new_url_stops_once_the_minute_budget_is_spent(self) -> None:
        self._spend_the_budget()

        with patch("products.workflows.backend.services.sns_verification.requests.get") as get:
            get.return_value.content = _CERT_PEM
            assert _fetch_signing_cert(_CERT_URL) is None

        assert get.call_count == 0

    def test_a_url_that_has_verified_before_is_refetched_even_with_the_budget_spent(self) -> None:
        # Otherwise junk URLs could spend the budget every minute and starve the real certificate's
        # hourly refresh, taking the webhook down for as long as the flood lasted.
        remember_verified_cert_url(_CERT_URL)
        self._spend_the_budget()

        with patch("products.workflows.backend.services.sns_verification.requests.get") as get:
            get.return_value.content = _CERT_PEM
            assert _fetch_signing_cert(_CERT_URL) == _CERT_PEM

        assert get.call_count == 1

    def test_a_verified_message_marks_its_cert_url_known(self) -> None:
        with patch("products.workflows.backend.services.sns_verification._fetch_signing_cert", return_value=_CERT_PEM):
            assert verify_sns_message(_signed_notification()) is True

        self._spend_the_budget()
        with patch("products.workflows.backend.services.sns_verification.requests.get") as get:
            get.return_value.content = _CERT_PEM
            assert _fetch_signing_cert(_CERT_URL) == _CERT_PEM

        assert get.call_count == 1
