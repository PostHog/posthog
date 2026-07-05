import hmac
import json
import time
import hashlib

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from products.tasks.backend.logic.linear_agent.parsing import (
    parse_agent_trigger,
    verify_linear_signature,
    webhook_timestamp_valid,
)

WEBHOOK_SECRET = "test-linear-webhook-secret"


def sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def notification_payload(
    action: str = "issueAssignedToYou",
    organization_id: str = "lin-org-1",
    timestamp_ms: int | None = None,
    **issue_overrides,
) -> dict:
    issue = {
        "id": "issue-uuid-1",
        "identifier": "ENG-42",
        "title": "Fix the thing",
        "url": "https://linear.app/acme/issue/ENG-42/fix-the-thing",
        **issue_overrides,
    }
    return {
        "type": "AppUserNotification",
        "action": action,
        "organizationId": organization_id,
        "notification": {
            "type": action,
            "issue": issue,
            "actor": {"id": "user-1", "name": "Ada"},
        },
        "webhookId": "wh-1",
        "webhookTimestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
    }


def agent_session_payload(action: str = "created", organization_id: str = "lin-org-1") -> dict:
    return {
        "type": "AgentSessionEvent",
        "action": action,
        "organizationId": organization_id,
        "agentSession": {
            "id": "session-1",
            "issue": {
                "id": "issue-uuid-2",
                "identifier": "ENG-43",
                "title": "Add the feature",
                "description": "Details in the issue body",
                "url": "https://linear.app/acme/issue/ENG-43/add-the-feature",
            },
            "comment": {"id": "comment-1", "body": "please handle"},
            "creator": {"id": "user-2", "name": "Grace"},
        },
        "webhookId": "wh-2",
        "webhookTimestamp": int(time.time() * 1000),
    }


class TestLinearWebhookParsing(SimpleTestCase):
    def test_signature_round_trip(self):
        body = b'{"a": 1}'
        self.assertTrue(verify_linear_signature(body, sign(body), WEBHOOK_SECRET))
        self.assertFalse(verify_linear_signature(body, sign(body, "other-secret"), WEBHOOK_SECRET))
        self.assertFalse(verify_linear_signature(b'{"a": 2}', sign(body), WEBHOOK_SECRET))
        self.assertFalse(verify_linear_signature(body, None, WEBHOOK_SECRET))

    @parameterized.expand(
        [
            ("fresh", 0, True),
            ("day_old", -23 * 60 * 60, True),
            ("older_than_window", -25 * 60 * 60, False),
            ("far_future", 25 * 60 * 60, False),
        ]
    )
    def test_webhook_timestamp_window(self, _name, offset_seconds, expected):
        now = 1_750_000_000.0
        payload = {"webhookTimestamp": int((now + offset_seconds) * 1000)}
        self.assertEqual(webhook_timestamp_valid(payload, now=now), expected)

    def test_webhook_timestamp_missing_or_malformed_is_invalid(self):
        self.assertFalse(webhook_timestamp_valid({}))
        self.assertFalse(webhook_timestamp_valid({"webhookTimestamp": "1750000000000"}))

    def test_parses_assignment_notification(self):
        trigger = parse_agent_trigger(notification_payload(description="Do the fix"))
        assert trigger is not None
        self.assertEqual(trigger.kind, "assigned")
        self.assertEqual(trigger.organization_id, "lin-org-1")
        self.assertEqual(trigger.issue_id, "issue-uuid-1")
        self.assertEqual(trigger.issue_identifier, "ENG-42")
        self.assertEqual(trigger.issue_description, "Do the fix")
        self.assertEqual(trigger.actor_name, "Ada")
        self.assertIsNone(trigger.agent_session_id)

    def test_parses_comment_mention_notification(self):
        payload = notification_payload(action="issueCommentMention")
        payload["notification"]["comment"] = {"id": "c-1", "body": "@posthog-code please fix"}
        trigger = parse_agent_trigger(payload)
        assert trigger is not None
        self.assertEqual(trigger.kind, "mentioned")
        self.assertEqual(trigger.comment_body, "@posthog-code please fix")

    def test_parses_agent_session_created(self):
        trigger = parse_agent_trigger(agent_session_payload())
        assert trigger is not None
        self.assertEqual(trigger.kind, "assigned")
        self.assertEqual(trigger.agent_session_id, "session-1")
        self.assertEqual(trigger.issue_id, "issue-uuid-2")
        self.assertEqual(trigger.issue_description, "Details in the issue body")

    @parameterized.expand(
        [
            ("uninteresting_notification", notification_payload(action="issueNewComment")),
            ("agent_session_prompted", agent_session_payload(action="prompted")),
            ("missing_organization", notification_payload(organization_id="")),
            ("missing_issue_id", notification_payload(id="")),
            ("unknown_type", {"type": "Issue", "action": "update", "organizationId": "lin-org-1"}),
        ]
    )
    def test_non_actionable_payloads_return_none(self, _name, payload):
        self.assertIsNone(parse_agent_trigger(payload))


@override_settings(LINEAR_AGENT_WEBHOOK_SECRET=WEBHOOK_SECRET)
class TestLinearWebhookView(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def _post(self, payload: dict, signature: str | None = None, secret: str = WEBHOOK_SECRET, headers=None):
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Linear-Signature": signature if signature is not None else sign(body, secret)}
        request_headers.update(headers or {})
        return self.client.post(
            "/webhooks/linear/", data=body, content_type="application/json", headers=request_headers
        )

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_valid_delivery_is_enqueued(self, mock_delay):
        payload = notification_payload()
        response = self._post(payload)
        self.assertEqual(response.status_code, 202)
        mock_delay.assert_called_once_with(payload=payload)

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_rejects_bad_signature(self, mock_delay):
        response = self._post(notification_payload(), secret="wrong-secret")
        self.assertEqual(response.status_code, 403)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_rejects_stale_timestamp(self, mock_delay):
        payload = notification_payload(timestamp_ms=int((time.time() - 25 * 60 * 60) * 1000))
        response = self._post(payload)
        self.assertEqual(response.status_code, 403)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_unconfigured_secret_returns_500_not_accept(self, mock_delay):
        with override_settings(LINEAR_AGENT_WEBHOOK_SECRET=""):
            response = self._post(notification_payload())
        self.assertEqual(response.status_code, 500)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_invalid_json_returns_400(self, mock_delay):
        body = b"not-json"
        response = self.client.post(
            "/webhooks/linear/",
            data=body,
            content_type="application/json",
            headers={"Linear-Signature": sign(body)},
        )
        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_unhandled_type_is_acked_without_dispatch(self, mock_delay):
        payload = notification_payload()
        payload["type"] = "OAuthApp"
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_duplicate_delivery_is_dispatched_once(self, mock_delay):
        payload = notification_payload()
        headers = {"Linear-Delivery": "delivery-abc"}
        first = self._post(payload, headers=headers)
        second = self._post(payload, headers=headers)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        mock_delay.assert_called_once()

    @patch("products.tasks.backend.tasks.process_linear_agent_event.delay")
    def test_non_post_is_rejected(self, mock_delay):
        response = self.client.get("/webhooks/linear/")
        self.assertEqual(response.status_code, 405)
        mock_delay.assert_not_called()
