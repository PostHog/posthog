import hmac
import time
import hashlib

import pytest

from django.core.handlers.wsgi import WSGIRequest
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import SlackIntegrationError, validate_slack_request


def _make_signed_request(body: str, secret: str, timestamp: str | None = None) -> WSGIRequest:
    factory = RequestFactory()
    ts = timestamp or str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()

    request = factory.post(
        "/slack/event-callback",
        data=body,
        content_type="application/json",
        HTTP_X_SLACK_SIGNATURE=signature,
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
    )
    return request


class TestValidateSlackRequest(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid_signature", "test-secret", "test-secret", None, None),
            ("wrong_secret", "test-secret", "wrong-secret", None, "Invalid"),
            ("expired_timestamp", "test-secret", "test-secret", "1000000000", "Invalid"),
            ("future_timestamp", "test-secret", "test-secret", str(int(time.time()) + 3600), "Invalid"),
            ("empty_secret", "", "test-secret", None, "Not configured"),
            ("invalid_timestamp", "test-secret", "test-secret", "not-a-number", "Invalid"),
        ]
    )
    def test_validate_slack_request(self, _name, signing_secret, request_secret, timestamp, expected_error):
        body = '{"type": "url_verification"}'

        if timestamp == "not-a-number":
            factory = RequestFactory()
            request = factory.post(
                "/slack/event-callback",
                data=body,
                content_type="application/json",
                HTTP_X_SLACK_SIGNATURE="v0=fake",
                HTTP_X_SLACK_REQUEST_TIMESTAMP="not-a-number",
            )
        else:
            request = _make_signed_request(body, request_secret, timestamp)

        if expected_error:
            with pytest.raises(SlackIntegrationError, match=expected_error):
                validate_slack_request(request, signing_secret)
        else:
            validate_slack_request(request, signing_secret)

    def test_a_non_ascii_signature_header_is_rejected(self):
        # The header arrives decoded as latin-1, and comparing it as a str raises TypeError on a
        # non-ASCII code point, which an unauthenticated caller could turn into a 500.
        factory = RequestFactory()
        request = factory.post(
            "/slack/event-callback",
            data='{"type": "test"}',
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE="v0=é",
            HTTP_X_SLACK_REQUEST_TIMESTAMP=str(int(time.time())),
        )
        with pytest.raises(SlackIntegrationError, match="Invalid"):
            validate_slack_request(request, "test-secret")

    def test_a_body_that_is_not_utf_8_is_rejected(self):
        # The signed input is assembled as bytes, so a body Slack never sent fails the compare
        # instead of raising a decode error.
        factory = RequestFactory()
        request = factory.post(
            "/slack/event-callback",
            data=b"\xff\xfe",
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE="v0=" + "0" * 64,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=str(int(time.time())),
        )
        with pytest.raises(SlackIntegrationError, match="Invalid"):
            validate_slack_request(request, "test-secret")

    def test_missing_headers(self):
        factory = RequestFactory()
        request = factory.post(
            "/slack/event-callback",
            data='{"type": "test"}',
            content_type="application/json",
        )
        with pytest.raises(SlackIntegrationError, match="Invalid"):
            validate_slack_request(request, "test-secret")
