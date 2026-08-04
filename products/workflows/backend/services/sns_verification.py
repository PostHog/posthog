import re
import base64
import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

from django.core.cache import cache

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.x509 import load_pem_x509_certificate

logger = logging.getLogger(__name__)

# The signing cert must come from SNS itself — a signature check against an attacker-supplied cert
# proves nothing. Mirrors the cert-URL validation in the Node SES webhook
# (nodejs/src/cdp/services/messaging/helpers/ses.ts).
_SNS_HOST_RE = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$")

_CERT_CACHE_SECONDS = 60 * 60
_FETCH_TIMEOUT_SECONDS = 5

# Per https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html the string to
# sign is "Key\nValue\n" pairs in this exact order, skipping absent keys.
_SIGNED_KEYS_BY_TYPE = {
    "Notification": ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
    "SubscriptionConfirmation": ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"],
    "UnsubscribeConfirmation": ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"],
}


def is_valid_sns_url(url: str | None) -> bool:
    """True when the URL is HTTPS on a real *.amazonaws.com SNS host (cert or subscribe URL)."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and bool(_SNS_HOST_RE.match(parsed.hostname or ""))


def _fetch_signing_cert(cert_url: str) -> bytes | None:
    # Hashed: the URL's path is caller-supplied and unbounded, and cache backends reject or mangle
    # over-long keys.
    cache_key = f"sns_signing_cert_{hashlib.sha256(cert_url.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        response = requests.get(cert_url, timeout=_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to fetch SNS signing certificate", extra={"cert_url": cert_url})
        return None
    cache.set(cache_key, response.content, _CERT_CACHE_SECONDS)
    return response.content


def _string_to_sign(message: dict[str, Any]) -> str | None:
    keys = _SIGNED_KEYS_BY_TYPE.get(message.get("Type", ""))
    if keys is None:
        return None
    parts = []
    for key in keys:
        value = message.get(key)
        if value is None:
            continue
        parts.append(f"{key}\n{value}\n")
    return "".join(parts)


def verify_sns_message(message: dict[str, Any]) -> bool:
    """
    Verify an SNS message's authenticity: signing cert served by SNS over HTTPS, RSA signature over
    the canonical string-to-sign. Returns False (never raises) on any mismatch so callers fail
    closed. Signature proves "from AWS SNS" — callers must still check TopicArn against an
    allowlist to prove "from *our* topic".
    """
    # Only SignatureVersion 2 (SHA256) is accepted. Version 1 signs with SHA1, which is not
    # collision resistant — and since we own the SNS topic, we simply configure it with
    # SignatureVersion=2 (a one-time SetTopicAttributes call, in the rollout runbook) instead of
    # ever verifying SHA1 here.
    if message.get("SignatureVersion") != "2":
        # SNS defaults topics to version 1, so this is the shape a missing SetTopicAttributes step
        # takes: every delivery rejected. Logged distinctly so that reads as misconfiguration
        # rather than as an attack.
        logger.warning(
            "Rejected SNS message with unsupported signature version",
            extra={"signature_version": message.get("SignatureVersion")},
        )
        return False
    cert_url = message.get("SigningCertURL")
    if not isinstance(cert_url, str) or not is_valid_sns_url(cert_url):
        return False
    string_to_sign = _string_to_sign(message)
    if string_to_sign is None:
        return False
    try:
        signature = base64.b64decode(message.get("Signature", ""))
    except (ValueError, TypeError):
        return False
    cert_pem = _fetch_signing_cert(cert_url)
    if cert_pem is None:
        return False
    try:
        public_key = load_pem_x509_certificate(cert_pem).public_key()
        if not isinstance(public_key, RSAPublicKey):
            return False
        public_key.verify(signature, string_to_sign.encode(), padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False
    except Exception:
        logger.exception("SNS signature verification errored")
        return False
