import hmac
import json
import hashlib

import pytest
from unittest.mock import patch

from django.test import RequestFactory, override_settings

from products.stamphog.backend.presentation.webhooks import stamphog_github_webhook

WEBHOOK_SECRET = "test-webhook-secret"


def _signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _request(body: bytes, *, event: str = "pull_request", delivery_id: str = "delivery-1", signature: str | None):
    factory = RequestFactory()
    headers = {"HTTP_X_GITHUB_EVENT": event, "HTTP_X_GITHUB_DELIVERY": delivery_id}
    if signature is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature
    return factory.post("/stamphog/webhook/", data=body, content_type="application/json", **headers)


@override_settings(STAMPHOG_GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
@patch("products.stamphog.backend.presentation.webhooks.process_pull_request_event.delay")
def test_valid_pull_request_event_enqueues_and_returns_202(mock_delay):
    body = json.dumps({"action": "opened"}).encode("utf-8")
    request = _request(body, signature=_signature(body, WEBHOOK_SECRET))

    response = stamphog_github_webhook(request)

    assert response.status_code == 202
    mock_delay.assert_called_once_with(payload={"action": "opened"}, delivery_id="delivery-1")


@override_settings(STAMPHOG_GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
@patch("products.stamphog.backend.presentation.webhooks.process_pull_request_event.delay")
def test_non_pull_request_event_is_acked_without_enqueueing(mock_delay):
    body = json.dumps({"action": "created"}).encode("utf-8")
    request = _request(body, event="issue_comment", signature=_signature(body, WEBHOOK_SECRET))

    response = stamphog_github_webhook(request)

    assert response.status_code == 200
    mock_delay.assert_not_called()


@pytest.mark.parametrize(
    "signature",
    [None, "sha256=" + "0" * 64],
    ids=["missing_signature", "wrong_signature"],
)
@override_settings(STAMPHOG_GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
@patch("products.stamphog.backend.presentation.webhooks.process_pull_request_event.delay")
def test_invalid_signature_is_rejected(mock_delay, signature):
    body = json.dumps({"action": "opened"}).encode("utf-8")
    request = _request(body, signature=signature)

    response = stamphog_github_webhook(request)

    assert response.status_code == 403
    mock_delay.assert_not_called()


@override_settings(STAMPHOG_GITHUB_WEBHOOK_SECRET="")
def test_missing_secret_configuration_returns_500():
    body = json.dumps({"action": "opened"}).encode("utf-8")
    request = _request(body, signature=_signature(body, "irrelevant"))

    response = stamphog_github_webhook(request)

    assert response.status_code == 500
