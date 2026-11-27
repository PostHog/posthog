import hmac
import json
import hashlib
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.http.response import HttpResponseBase
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry

WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_PATH = "/webhooks/stamphog/github"

PULL_REQUEST_DELAY = "products.stamphog.backend.facade.tasks.process_pull_request_event.delay"
INSTALLATION_DELAY = "products.stamphog.backend.facade.tasks.process_installation_event.delay"
ROUTING_DELAY = "products.stamphog.backend.facade.tasks.route_pull_request_reviewers.delay"
BROADCAST_REQUEST_DELAY = "products.stamphog.backend.facade.tasks.refresh_broadcast_requests_for_pull_request.delay"

POSTHOG_APP_SECRET = "test-posthog-app-secret"
POSTHOG_APP_PATH = "/webhooks/github"
PULL_REQUEST_FIELDS = {"repository": {"full_name": "acme/widgets"}, "pull_request": {"number": 7}}


def _signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@override_settings(STAMPHOG_GITHUB_APP_WEBHOOK_SECRET=WEBHOOK_SECRET)
class TestStamphogGitHubWebhook(SimpleTestCase):
    def setUp(self) -> None:
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
    ) -> HttpResponseBase:
        headers: dict[str, str] = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery_id}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        return self.client.post(WEBHOOK_PATH, data=body, content_type="application/json", headers=headers)

    @parameterized.expand(
        [
            ("pull_request", "opened", PULL_REQUEST_DELAY, INSTALLATION_DELAY, True),
            ("pull_request", "ready_for_review", PULL_REQUEST_DELAY, INSTALLATION_DELAY, True),
            ("pull_request", "synchronize", PULL_REQUEST_DELAY, INSTALLATION_DELAY, True),
            ("pull_request", "edited", PULL_REQUEST_DELAY, INSTALLATION_DELAY, False),
            ("installation", "opened", INSTALLATION_DELAY, PULL_REQUEST_DELAY, False),
            ("installation_repositories", "opened", INSTALLATION_DELAY, PULL_REQUEST_DELAY, False),
        ]
    )
    def test_a_verified_delivery_enqueues_the_task_that_event_routes_to(
        self, event: str, action: str, expected_task: str, other_task: str, routes: bool
    ) -> None:
        body = json.dumps({"action": action}).encode("utf-8")

        with (
            patch(expected_task) as expected_delay,
            patch(other_task) as other_delay,
            patch(ROUTING_DELAY) as routing_delay,
        ):
            response = self._post(body, event=event, signature=_signature(body, WEBHOOK_SECRET))

        assert response.status_code == 202
        expected_delay.assert_called_once_with(payload={"action": action}, delivery_id="delivery-1")
        other_delay.assert_not_called()
        # Routing is its own consumer, queued for the actions that ask for reviews and for a push.
        assert routing_delay.call_count == (1 if routes else 0)

    @patch(ROUTING_DELAY)
    @patch(PULL_REQUEST_DELAY)
    def test_a_redelivery_reaches_the_task_again_because_the_consumer_opts_out_of_dedup(
        self, mock_delay, mock_routing_delay
    ) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")

        for _ in range(2):
            assert self._post(body, signature=_signature(body, WEBHOOK_SECRET)).status_code == 202

        # The task keys its resume path on the delivery id, so GitHub's redelivery is how a run
        # that never finished gets picked up. An ingress dedup mark would hold that off for 24 h.
        assert mock_delay.call_count == 2
        assert mock_routing_delay.call_count == 2

    @patch(PULL_REQUEST_DELAY)
    @patch(INSTALLATION_DELAY)
    def test_an_event_type_the_app_does_not_register_is_acked_without_enqueueing(
        self, mock_installation_delay, mock_pull_request_delay
    ) -> None:
        body = json.dumps({"action": "created"}).encode("utf-8")

        response = self._post(body, event="issue_comment", signature=_signature(body, WEBHOOK_SECRET))

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

        response = self._post(body, signature=signature)

        assert response.status_code == 403
        mock_delay.assert_not_called()

    @patch(PULL_REQUEST_DELAY)
    def test_a_signed_but_unparseable_body_is_rejected(self, mock_delay) -> None:
        body = b"{not json"

        response = self._post(body, signature=_signature(body, WEBHOOK_SECRET))

        assert response.status_code == 400
        mock_delay.assert_not_called()

    @patch(PULL_REQUEST_DELAY)
    def test_a_non_post_is_refused(self, mock_delay) -> None:
        response = self.client.get(WEBHOOK_PATH)

        assert response.status_code == 405
        mock_delay.assert_not_called()

    @override_settings(STAMPHOG_GITHUB_APP_WEBHOOK_SECRET="")
    @patch(PULL_REQUEST_DELAY)
    def test_a_missing_app_secret_is_500_rather_than_a_signature_failure(self, mock_delay) -> None:
        body = json.dumps({"action": "opened"}).encode("utf-8")

        response = self._post(body, signature=_signature(body, "irrelevant"))

        assert response.status_code == 500
        mock_delay.assert_not_called()

    @parameterized.expand(
        [
            # The review task refreshes after a head change or a retarget, once it decided on a run.
            ("synchronize", {}, False),
            ("closed", {}, True),
            ("reopened", {}, False),
            ("review_requested", {}, True),
            ("edited", {"changes": {"base": {"ref": {"from": "main"}}}}, False),
            ("edited", {"changes": {"title": {"from": "Old"}}}, False),
            ("opened", {}, False),
            ("labeled", {}, False),
        ]
    )
    def test_a_pull_request_change_a_card_shows_refreshes_its_broadcast_requests(
        self, action: str, extra: dict, refreshes: bool
    ) -> None:
        payload = {"action": action, "installation": {"id": 42}, **PULL_REQUEST_FIELDS, **extra}
        body = json.dumps(payload).encode("utf-8")

        with (
            patch(PULL_REQUEST_DELAY),
            patch(ROUTING_DELAY),
            patch(BROADCAST_REQUEST_DELAY) as broadcast_request_delay,
        ):
            assert self._post(body, signature=_signature(body, WEBHOOK_SECRET)).status_code == 202

        if refreshes:
            # Stamphog's own installation names the one repo config that owns the repository.
            broadcast_request_delay.assert_called_once_with(
                repository="acme/widgets", pr_number=7, installation_id="42"
            )
        else:
            broadcast_request_delay.assert_not_called()


class TestPostHogAppReviewWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)
        # The other products' review consumers run on the same delivery and read their own tables.
        patches: tuple[tuple[str, dict[str, Any]], ...] = (
            (
                "posthog.credentials_service.instance_settings.get_instance_setting",
                {"return_value": POSTHOG_APP_SECRET},
            ),
            ("products.workflows.backend.facade.api.accept_github_event", {}),
            ("products.tasks.backend.facade.api.accept_github_pull_request_review", {}),
        )
        for target, kwargs in patches:
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            ("approved", "submitted", "approved", "User", True),
            ("changes_requested", "submitted", "changes_requested", "User", True),
            ("dismissed", "dismissed", "dismissed", "User", True),
            ("comment_only", "submitted", "commented", "User", False),
            ("bot_review", "submitted", "approved", "Bot", False),
            ("edited", "edited", "approved", "User", False),
        ]
    )
    def test_a_review_that_can_move_an_approval_refreshes_the_broadcast_requests(
        self, _name: str, action: str, state: str, user_type: str, refreshes: bool
    ) -> None:
        payload = {
            "action": action,
            "installation": {"id": 99},
            "review": {"state": state, "user": {"login": "maintainer", "type": user_type}},
            **PULL_REQUEST_FIELDS,
        }
        body = json.dumps(payload).encode("utf-8")

        with patch(BROADCAST_REQUEST_DELAY) as broadcast_request_delay:
            response = self.client.post(
                POSTHOG_APP_PATH,
                data=body,
                content_type="application/json",
                headers={
                    "X-GitHub-Event": "pull_request_review",
                    "X-GitHub-Delivery": "delivery-review",
                    "X-Hub-Signature-256": _signature(body, POSTHOG_APP_SECRET),
                },
            )

        assert response.status_code == 202
        if refreshes:
            # The PostHog App's installation is not stamphog's, so it must not narrow the match.
            broadcast_request_delay.assert_called_once_with(repository="acme/widgets", pr_number=7, installation_id="")
        else:
            broadcast_request_delay.assert_not_called()
