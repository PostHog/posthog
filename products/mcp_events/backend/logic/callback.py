import ssl
import hmac
import json
import time
import base64
import hashlib
import secrets
import binascii
from urllib.parse import urlsplit

import httpx
from rest_framework.exceptions import ValidationError

from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import validate_url_and_pin_ips

from products.mcp_events.backend.facade.contracts import MCPCallbackError


def signing_key(secret: str) -> bytes:
    if not secret.startswith("whsec_"):
        raise ValidationError({"secret": "Use a whsec_ signing secret supplied by the receiving client."})
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValidationError({"secret": "The signing secret must contain valid base64."}) from error
    if not 24 <= len(key) <= 64:
        raise ValidationError({"secret": "The signing secret must decode to 24 to 64 bytes."})
    return key


def validate_callback_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ValidationError({"url": "Use an HTTPS callback URL without credentials or a fragment."}) from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValidationError({"url": "Use an HTTPS callback URL without credentials or a fragment."})
    return url


def verify_callback(*, subscription_id: str, url: str, secret: str) -> None:
    """Send a signed challenge and require the receiver to echo it, before any event goes to the URL."""
    validate_callback_url(url)
    challenge = secrets.token_urlsafe(32)
    body = json.dumps({"type": "verification", "challenge": challenge}, separators=(",", ":"))
    webhook_id = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    signature = base64.b64encode(
        hmac.new(signing_key(secret), f"{webhook_id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "Content-Type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{signature}",
        "X-MCP-Subscription-Id": subscription_id,
    }
    try:
        verdict = validate_url_and_pin_ips(url)
        if not verdict.allowed:
            raise SSRFBlockedError
        with pinned_client(
            url, verdict.pinned_ips, total_timeout=10, max_response_bytes=8192, timeout=10, follow_redirects=False
        ) as client:
            response = client.post(url, content=body, headers=headers)
            if not 200 <= response.status_code < 300:
                raise MCPCallbackError("http_4xx" if response.status_code < 500 else "http_5xx")
            result = response.json()
            echoed = result.get("challenge") if isinstance(result, dict) else None
            if not isinstance(echoed, str) or not hmac.compare_digest(echoed.encode(), challenge.encode()):
                raise MCPCallbackError("challenge_failed")
    except httpx.InvalidURL:
        raise MCPCallbackError("connection_failed") from None
    except httpx.TimeoutException:
        raise MCPCallbackError("timeout") from None
    except httpx.DecodingError:
        raise MCPCallbackError("challenge_failed") from None
    except httpx.HTTPError as error:
        cause: BaseException | None = error
        while cause is not None:
            if isinstance(cause, ssl.SSLError):
                raise MCPCallbackError("tls_error") from None
            cause = cause.__cause__
        raise MCPCallbackError("connection_failed") from None
    except SSRFBlockedError:
        raise MCPCallbackError("connection_failed") from None
    except (ValueError, UnicodeDecodeError):
        raise MCPCallbackError("challenge_failed") from None
