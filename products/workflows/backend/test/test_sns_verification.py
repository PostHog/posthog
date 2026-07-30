import base64
import datetime
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from parameterized import parameterized

from products.workflows.backend.services.sns_verification import is_valid_sns_url, verify_sns_message

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
        "SignatureVersion": "1",
        "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
    }
    string_to_sign = "".join(
        f"{key}\n{message[key]}\n" for key in ["Message", "MessageId", "Timestamp", "TopicArn", "Type"]
    )
    signature = _KEY.sign(string_to_sign.encode(), padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
    message["Signature"] = base64.b64encode(signature).decode()
    message.update(tamper or {})
    return message


class TestSnsVerification(TestCase):
    def _verify(self, message: dict[str, Any]) -> bool:
        with patch("products.workflows.backend.services.sns_verification._fetch_signing_cert", return_value=_CERT_PEM):
            return verify_sns_message(message)

    def test_accepts_a_correctly_signed_notification(self):
        assert self._verify(_signed_notification()) is True

    @parameterized.expand(
        [
            ("tampered_message", {"Message": '{"source":"aws.ses","evil":true}'}),
            ("tampered_topic", {"TopicArn": "arn:aws:sns:us-east-1:666:other"}),
            ("garbage_signature", {"Signature": base64.b64encode(b"nope").decode()}),
            ("cert_not_from_sns", {"SigningCertURL": "https://attacker.example.com/cert.pem"}),
            ("cert_over_http", {"SigningCertURL": "http://sns.us-east-1.amazonaws.com/cert.pem"}),
            ("unknown_type", {"Type": "SomethingElse"}),
        ]
    )
    def test_rejects(self, _name: str, tamper: dict[str, Any]):
        assert self._verify(_signed_notification(tamper)) is False

    @parameterized.expand(
        [
            ("sns_regional", "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService.pem", True),
            ("subdomain_spoof", "https://sns.us-east-1.amazonaws.com.evil.com/cert.pem", False),
            ("wrong_service", "https://s3.us-east-1.amazonaws.com/cert.pem", False),
            ("empty", "", False),
            ("none", None, False),
        ]
    )
    def test_url_validation(self, _name: str, url: str | None, expected: bool):
        assert is_valid_sns_url(url) is expected
