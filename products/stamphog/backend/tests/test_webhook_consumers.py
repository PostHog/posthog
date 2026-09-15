import hmac
import json
import hashlib
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry

from products.stamphog.backend.facade.webhooks import stamphog_github_webhook

WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_PATH = "/webhooks/stamphog/github"

PULL_REQUEST_DELAY = "products.stamphog.backend.facade.tasks.process_pull_request_event.delay"
INSTALLATION_DELAY = "products.stamphog.backend.facade.tasks.process_installation_event.delay"


def _signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@override_settings(STAMPHOG_GITHUB_APP_WEBHOOK_SECRET=WEBHOOK_SECRET)
class TestStamphogGitHubWebhook(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        # The registry is cached for the process and the dedup marks sit in the cache; both would
        # otherwise carry another test's state into this one.
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)

    def _post(
        self,
        body: bytes,
        *,
        signature: str | None,
        event: str = "pull_request",
        delivery_id: str = "delivery-1",
    ) -> Any:
        headers: dict[str, str] = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery_id}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        return self.factory.post(WEBHOOK_PATH, data=body, content_type="application/json", headers=headers)

    @parameterized.expand(
        [
            ("pull_request", PULL_REQUEST_DELAY, INSTALLATION_DELAY),
            ("installation", INSTALLATION_DELAY, PULL_REQUEST_DELAY),
            ("installation_repositories", INSTALLATION_DELAY, PULL_REQUEST_DELAY),
        ]
    )
    def test_a_verified_delivery_enqueues_the_task_that_event_routes_to(
        self, event: str, expected_task: str, other_task: str
    ) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")
        request = self._post(body, event=event, signature=_signature(body, WEBHOOK_SECRET))

        with patch(expected_task) as expected_delay, patch(other_task) as other_delay:
            response = stamphog_github_webhook(request)

        assert response.status_code == 202
        expected_delay.assert_called_once_with(payload={"action": "opened"}, delivery_id="delivery-1")
        other_delay.assert_not_called()

    @patch(PULL_REQUEST_DELAY)
    def test_a_redelivery_reaches_the_task_again_because_the_consumer_opts_out_of_dedup(self, mock_delay) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")

        for _ in range(2):
            request = self._post(body, signature=_signature(body, WEBHOOK_SECRET))
            assert stamphog_github_webhook(request).status_code == 202

        # The task keys its resume path on the delivery id, so GitHub's redelivery is how a run
        # that never finished gets picked up. An ingress dedup mark would hold that off for 24 h.
        assert mock_delay.call_count == 2

    @patch(PULL_REQUEST_DELAY)
    @patch(INSTALLATION_DELAY)
    def test_an_event_type_the_app_does_not_register_is_acked_without_enqueueing(
        self, mock_installation_delay, mock_pull_request_delay
    ) -> None:
        body = json.dumps({"action": "created"}).encode("utf-8")
        request = self._post(body, event="issue_comment", signature=_signature(body, WEBHOOK_SECRET))

        response = stamphog_github_webhook(request)

        assert response.status_code == 202
        mock_pull_request_delay.assert_not_called()
        mock_installation_delay.assert_not_called()

    @parameterized.expand(
        [
            ("missing_signature", None),
            ("wrong_signature", "sha256=" + "0" * 64),
        ]
    )
    @patch(PULL_REQUEST_DELAY)
    def test_an_invalid_signature_is_rejected(self, _name: str, signature: str | None, mock_delay) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")
        request = self._post(body, signature=signature)

        response = stamphog_github_webhook(request)

        assert response.status_code == 403
        mock_delay.assert_not_called()

    @patch(PULL_REQUEST_DELAY)
    def test_a_signed_but_unparseable_body_is_rejected(self, mock_delay) -> None:
        body = b"{not json"
        request = self._post(body, signature=_signature(body, WEBHOOK_SECRET))

        response = stamphog_github_webhook(request)

        assert response.status_code == 400
        mock_delay.assert_not_called()

    @patch(PULL_REQUEST_DELAY)
    def test_a_non_post_is_refused(self, mock_delay) -> None:
        response = stamphog_github_webhook(self.factory.get(WEBHOOK_PATH))

        assert response.status_code == 405
        mock_delay.assert_not_called()

    @override_settings(STAMPHOG_GITHUB_APP_WEBHOOK_SECRET="")
    @patch(PULL_REQUEST_DELAY)
    def test_a_missing_app_secret_is_500_rather_than_a_signature_failure(self, mock_delay) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")
        request = self._post(body, signature=_signature(body, "irrelevant"))

        response = stamphog_github_webhook(request)

        assert response.status_code == 500
        mock_delay.assert_not_called()
