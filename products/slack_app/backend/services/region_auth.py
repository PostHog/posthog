"""Region-to-region request signing for cross-region chat provider probes.

Both PostHog Cloud regions (US and EU) provision the same per-provider secret, so one
region can HMAC-sign a small JSON body and the other can verify it without trusting the
transport. The construction is the same v0 HMAC-SHA256 scheme Slack uses for webhooks,
carried in provider-neutral headers so non-Slack chat providers can reuse it.
"""

import hmac
import time
import hashlib

from django.http import HttpRequest

from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import SlackIntegration, sign_slack_request

REGION_SIGNATURE_HEADER = "X-PostHog-Region-Signature"
REGION_TIMESTAMP_HEADER = "X-PostHog-Region-Timestamp"
_REGION_SIGNATURE_MAX_AGE_SECONDS = 300


class RegionAuthError(Exception):
    """The inbound cross-region request could not be authenticated."""


def sign_region_request(body: bytes, secret: str) -> tuple[str, str]:
    """Sign a request body for a cross-region probe; returns (signature, timestamp)."""
    return sign_slack_request(body, secret)


def validate_region_request(request: HttpRequest, secret: str) -> None:
    """Verify the neutral region signature headers, raising ``RegionAuthError`` on failure."""
    signature = request.headers.get(REGION_SIGNATURE_HEADER)
    timestamp = request.headers.get(REGION_TIMESTAMP_HEADER)

    if not secret or not signature or not timestamp:
        raise RegionAuthError("Invalid")

    try:
        if time.time() - float(timestamp) > _REGION_SIGNATURE_MAX_AGE_SECONDS:
            raise RegionAuthError("Expired")
    except ValueError:
        raise RegionAuthError("Invalid")

    sig_basestring = f"v0:{timestamp}:{request.body.decode('utf-8')}"
    expected = (
        "v0="
        + hmac.new(
            secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise RegionAuthError("Invalid")


def region_claims_secret(provider: str) -> str:
    """The shared US/EU secret used to sign cross-region claims probes for a provider."""
    if provider == "slack":
        return str(SlackIntegration.slack_config()["SLACK_APP_SIGNING_SECRET"])
    if provider == "telegram":
        return str(get_instance_setting("TELEGRAM_APP_WEBHOOK_SECRET"))
    raise RegionAuthError(f"Unknown chat provider: {provider}")
