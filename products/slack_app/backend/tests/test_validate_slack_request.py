import hmac
import time
import hashlib

import pytest

from django.test import RequestFactory, TestCase

from parameterized import parameterized

from posthog.models.integration import SlackIntegrationError, validate_slack_request


def _make_signed_request(body: str, secret: str, timestamp: str | None = None) -> object:
    factory = RequestFactory()
    ts = timestamp or str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()

    request = factory.post(
        "/slack/twig-event-callback",
        data=body,
        content_type="application/json",
        HTTP_X_SLACK_SIGNATURE=signature,
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
    )
    return request


class TestValidateSlackRequest(TestCase):
    @parameterized.expand(
        [
            ("valid_signature", "test-secret", "test-secret", None, None),
            ("wrong_secret", "test-secret", "wrong-secret", None, "Invalid"),
            ("expired_timestamp", "test-secret", "test-secret", "1000000000", "Expired"),
            ("empty_secret", "", "test-secret", None, "Invalid"),
            ("invalid_timestamp", "test-secret", "test-secret", "not-a-number", "Invalid"),
        ]
    )
    def test_validate_slack_request(self, _name, signing_secret, request_secret, timestamp, expected_error):
        body = '{"type": "url_verification"}'

        if timestamp == "not-a-number":
            factory = RequestFactory()
            request = factory.post(
                "/slack/twig-event-callback",
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

    def test_missing_headers(self):
        factory = RequestFactory()
        request = factory.post(
            "/slack/twig-event-callback",
            data='{"type": "test"}',
            content_type="application/json",
        )
        with pytest.raises(SlackIntegrationError, match="Invalid"):
            validate_slack_request(request, "test-secret")
