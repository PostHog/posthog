import hmac
import json
import hashlib

from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun


def generate_github_signature(payload: bytes, secret: str) -> str:
    """Generate a GitHub-style HMAC-SHA256 signature."""
    return (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )


class TestGitHubPRWebhook(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.webhook_secret = "test-webhook-secret"

        # Create test organization, team, and user
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-123")

        # Create a task and task run with a PR URL
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test description",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/posthog/posthog/pull/123"},
        )

    def _make_webhook_request(self, payload: dict, event_type: str = "pull_request"):
        """Helper to make a webhook request with proper signature."""
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = generate_github_signature(payload_bytes, self.webhook_secret)

        return self.client.post(
            "/webhooks/github/pr/",
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
            HTTP_X_GITHUB_EVENT=event_type,
        )

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.webhooks.posthoganalytics.capture")
    def test_pr_merged_webhook(self, mock_capture, mock_get_secret):
        """Test that a PR merged webhook creates a log entry and analytics event."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {
            "action": "closed",
            "pull_request": {
                "html_url": "https://github.com/posthog/posthog/pull/123",
                "merged": True,
            },
        }

        response = self._make_webhook_request(payload)

        self.assertEqual(response.status_code, 200)

        # Verify analytics was called
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "pr_merged")
        self.assertEqual(call_kwargs["properties"]["pr_url"], "https://github.com/posthog/posthog/pull/123")
        self.assertEqual(call_kwargs["properties"]["task_id"], str(self.task.id))
        self.assertEqual(call_kwargs["properties"]["run_id"], str(self.task_run.id))

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.webhooks.posthoganalytics.capture")
    def test_pr_closed_without_merge_webhook(self, mock_capture, mock_get_secret):
        """Test that a PR closed (not merged) webhook creates correct events."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {
            "action": "closed",
            "pull_request": {
                "html_url": "https://github.com/posthog/posthog/pull/123",
                "merged": False,
            },
        }

        response = self._make_webhook_request(payload)

        self.assertEqual(response.status_code, 200)

        # Verify analytics was called with pr_closed event
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "pr_closed")

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.webhooks.posthoganalytics.capture")
    def test_pr_opened_webhook(self, mock_capture, mock_get_secret):
        """Test that a PR opened webhook creates correct events."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {
            "action": "opened",
            "pull_request": {
                "html_url": "https://github.com/posthog/posthog/pull/123",
                "merged": False,
            },
        }

        response = self._make_webhook_request(payload)

        self.assertEqual(response.status_code, 200)

        # Verify analytics was called with pr_created event
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "pr_created")

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_invalid_signature_rejected(self, mock_get_secret):
        """Test that requests with invalid signatures are rejected."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {"action": "closed", "pull_request": {"html_url": "https://github.com/org/repo/pull/1"}}
        payload_bytes = json.dumps(payload).encode("utf-8")

        response = self.client.post(
            "/webhooks/github/pr/",
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=invalid",
            HTTP_X_GITHUB_EVENT="pull_request",
        )

        self.assertEqual(response.status_code, 403)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_missing_signature_rejected(self, mock_get_secret):
        """Test that requests without signatures are rejected."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {"action": "closed", "pull_request": {"html_url": "https://github.com/org/repo/pull/1"}}

        response = self.client.post(
            "/webhooks/github/pr/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="pull_request",
        )

        self.assertEqual(response.status_code, 403)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.webhooks.posthoganalytics.capture")
    def test_unknown_pr_url_returns_200(self, mock_capture, mock_get_secret):
        """Test that webhooks for unknown PR URLs return 200 but don't emit events."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {
            "action": "closed",
            "pull_request": {
                "html_url": "https://github.com/unknown/repo/pull/999",
                "merged": True,
            },
        }

        response = self._make_webhook_request(payload)

        self.assertEqual(response.status_code, 200)
        mock_capture.assert_not_called()

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_non_pr_event_ignored(self, mock_get_secret):
        """Test that non-pull_request events are acknowledged but ignored."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {"action": "created", "issue": {"html_url": "https://github.com/org/repo/issues/1"}}

        response = self._make_webhook_request(payload, event_type="issues")

        self.assertEqual(response.status_code, 200)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_ignored_pr_actions(self, mock_get_secret):
        """Test that PR actions other than opened/closed are acknowledged but ignored."""
        mock_get_secret.return_value = self.webhook_secret

        for action in ["edited", "reopened", "synchronize", "labeled"]:
            payload = {
                "action": action,
                "pull_request": {
                    "html_url": "https://github.com/posthog/posthog/pull/123",
                    "merged": False,
                },
            }

            response = self._make_webhook_request(payload)
            self.assertEqual(response.status_code, 200, f"Failed for action: {action}")

    def test_webhook_secret_not_configured(self):
        """Test that webhook returns 500 if secret is not configured."""
        with patch("products.tasks.backend.webhooks.get_github_webhook_secret", return_value=None):
            payload = {"action": "closed", "pull_request": {"html_url": "https://github.com/org/repo/pull/1"}}

            response = self.client.post(
                "/webhooks/github/pr/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_X_GITHUB_EVENT="pull_request",
            )

            self.assertEqual(response.status_code, 500)

    def test_method_not_allowed(self):
        """Test that non-POST methods are rejected."""
        response = self.client.get("/webhooks/github/pr/")
        self.assertEqual(response.status_code, 405)
