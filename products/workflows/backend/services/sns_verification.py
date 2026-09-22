import re
import time
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

# Cert URLs are one fixed shape; a message whose path is anything else cannot be from SNS, and
# checking it here means such a message is rejected without an outbound request.
_CERT_PATH_RE = re.compile(r"^/SimpleNotificationService-[A-Za-z0-9]{8,64}\.pem$")

_CERT_CACHE_SECONDS = 60 * 60
_CERT_FAILURE_CACHE_SECONDS = 60
_FETCH_TIMEOUT_SECONDS = 5
# Bounds what a flood of varied cert URLs can make us do: over budget we fail closed. The budget
# covers only URLs that have never verified a message, so exhausting it cannot stop the certificate
# a real topic signs with from being refreshed — see _fetch_signing_cert.
_MAX_UNKNOWN_CERT_FETCHES_PER_MINUTE = 10
# A cert URL that has verified a message came from SNS, so it stays trusted well past the rotation
# interval and its refetch is never rationed.
_KNOWN_CERT_URL_SECONDS = 60 * 60 * 24 * 30
_FETCH_FAILED = "failed"

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
    if parsed.scheme != "https" or not parsed.hostname or not _SNS_HOST_RE.match(parsed.hostname):
        return False
    # SNS only ever serves 443. Without this an SNS hostname on a dead port passes validation, and
    # each such URL holds a request for the full fetch timeout.
    try:
        return parsed.port in (None, 443)
    except ValueError:
        # urlparse defers parsing the port, so a non-numeric one raises here rather than above.
        return False


def is_valid_sns_cert_url(url: str | None) -> bool:
    """True when the URL is one SNS could actually serve a signing certificate from."""
    return is_valid_sns_url(url) and bool(_CERT_PATH_RE.match(urlparse(url or "").path))


def _url_digest(cert_url: str) -> str:
    # Hashed: the URL's path is caller-supplied and unbounded, and cache backends reject or mangle
    # over-long keys.
    return hashlib.sha256(cert_url.encode()).hexdigest()


def _claim_unknown_cert_fetch_slot() -> bool:
    # One counter shared across web workers, so the ceiling holds for the deployment rather than
    # per process.
    bucket_key = f"sns_cert_fetch_budget_{int(time.time()) // 60}"
    cache.add(bucket_key, 0, 120)
    try:
        return cache.incr(bucket_key) <= _MAX_UNKNOWN_CERT_FETCHES_PER_MINUTE
    except ValueError:
        # The bucket expired between the add and the incr, so this is effectively a fresh minute.
        return True


def remember_verified_cert_url(cert_url: str) -> None:
    """Record that this URL served a certificate that verified a message, exempting its refetches."""
    cache.set(f"sns_known_cert_url_{_url_digest(cert_url)}", True, _KNOWN_CERT_URL_SECONDS)


def _fetch_signing_cert(cert_url: str) -> bytes | None:
    cache_key = f"sns_signing_cert_{_url_digest(cert_url)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return None if cached == _FETCH_FAILED else cached
    # Only novel URLs are rationed. Rationing every fetch would hand an attacker an outage: spend the
    # budget on well-shaped junk URLs each minute, and the real certificate could not be refreshed
    # once its hour expired.
    is_known = cache.get(f"sns_known_cert_url_{_url_digest(cert_url)}") is not None
    if not is_known and not _claim_unknown_cert_fetch_slot():
        logger.warning("Skipped SNS signing certificate fetch, per-minute budget for new URLs exhausted")
        return None
    try:
        response = requests.get(cert_url, timeout=_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to fetch SNS signing certificate", extra={"cert_url": cert_url})
        # Remember the failure, or a repeated bad URL buys a fresh request every time.
        cache.set(cache_key, _FETCH_FAILED, _CERT_FAILURE_CACHE_SECONDS)
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
    if not isinstance(cert_url, str) or not is_valid_sns_cert_url(cert_url):
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
        remember_verified_cert_url(cert_url)
        return True
    except InvalidSignature:
        return False
    except Exception:
        logger.exception("SNS signature verification errored")
        return False
