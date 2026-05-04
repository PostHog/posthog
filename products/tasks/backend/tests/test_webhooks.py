import hmac
import json
import hashlib
from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.webhooks import find_task_run


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
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="test@example.com", distinct_id="user-123")
        cls.task = Task.objects.create(
            team=cls.team,
            created_by=cls.user,
            title="Test Task",
            description="Test description",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )
        cls.task_run = TaskRun.objects.create(
            task=cls.task,
            team=cls.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/posthog/posthog/pull/123"},
        )

    def setUp(self):
        self.client = APIClient()
        self.webhook_secret = "test-webhook-secret"

    def _make_webhook_request(self, payload: dict, event_type: str = "pull_request"):
        """Helper to make a webhook request with proper signature."""
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = generate_github_signature(payload_bytes, self.webhook_secret)

        return self.client.post(
            "/webhooks/github/pr/",
            data=payload_bytes,
            content_type="application/json",
            headers={"x-hub-signature-256": signature, "x-github-event": event_type},
        )

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_pr_merged_webhook(self, mock_capture, mock_get_secret):
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

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "pr_merged")
        self.assertEqual(call_kwargs["properties"]["pr_url"], "https://github.com/posthog/posthog/pull/123")
        self.assertEqual(call_kwargs["properties"]["task_id"], str(self.task.id))
        self.assertEqual(call_kwargs["properties"]["run_id"], str(self.task_run.id))

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_pr_closed_without_merge_webhook(self, mock_capture, mock_get_secret):
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

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "pr_closed")

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_pr_opened_webhook(self, mock_capture, mock_get_secret):
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
            headers={"x-hub-signature-256": "sha256=invalid", "x-github-event": "pull_request"},
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
            headers={"x-github-event": "pull_request"},
        )

        self.assertEqual(response.status_code, 403)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_unknown_pr_url_returns_200(self, mock_capture, mock_get_secret):
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
                headers={"x-github-event": "pull_request"},
            )

            self.assertEqual(response.status_code, 500)

    def test_method_not_allowed(self):
        """Test that non-POST methods are rejected."""
        response = self.client.get("/webhooks/github/pr/")
        self.assertEqual(response.status_code, 405)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_webhook_does_not_attribute_foreign_repo_pr_to_unrelated_run(self, mock_capture, mock_get_secret):
        # Regression: a PR opened on a repo that has no matching TaskRun must
        # not fall through to a branch-only lookup that attributes the event
        # to an unrelated team's run with a colliding branch name.
        mock_get_secret.return_value = self.webhook_secret
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="main",
        )

        payload = {
            "action": "opened",
            "repository": {"full_name": "ArkeroAI/arkero2"},
            "pull_request": {
                "html_url": "https://github.com/ArkeroAI/arkero2/pull/533",
                "merged": False,
                "head": {"ref": "main"},
            },
        }

        response = self._make_webhook_request(payload)

        self.assertEqual(response.status_code, 200)
        mock_capture.assert_not_called()


class TestFindTaskRun(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-123")
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test description",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )

    def test_finds_by_pr_url(self):
        task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/posthog/posthog/pull/123"},
        )
        result = find_task_run(pr_url="https://github.com/posthog/posthog/pull/123")
        self.assertEqual(result, task_run)

    def test_finds_by_branch_when_no_pr_url_match(self):
        task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="feature/my-branch",
        )
        result = find_task_run(branch="feature/my-branch", repository="posthog/posthog")
        self.assertEqual(result, task_run)

    def test_pr_url_takes_priority_over_branch(self):
        pr_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/posthog/posthog/pull/123"},
            branch="feature/other-branch",
        )
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="feature/my-branch",
        )
        result = find_task_run(
            pr_url="https://github.com/posthog/posthog/pull/123",
            branch="feature/my-branch",
            repository="posthog/posthog",
        )
        self.assertEqual(result, pr_run)

    def test_falls_back_to_branch_when_pr_url_not_found(self):
        branch_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="feature/my-branch",
        )
        result = find_task_run(
            pr_url="https://github.com/posthog/posthog/pull/999",
            branch="feature/my-branch",
            repository="posthog/posthog",
        )
        self.assertEqual(result, branch_run)

    def test_returns_none_when_no_match(self):
        result = find_task_run(pr_url="https://github.com/posthog/posthog/pull/999")
        self.assertIsNone(result)

    def test_returns_none_with_no_args(self):
        result = find_task_run()
        self.assertIsNone(result)

    def test_branch_fallback_requires_repository(self):
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="main",
        )
        # Without a repository the branch fallback must not match — bare branch
        # names like "main" collide across every team in the database.
        self.assertIsNone(find_task_run(branch="main"))

    def test_branch_fallback_does_not_match_other_repositories(self):
        # The task's repository is "posthog/posthog"; a webhook from a foreign
        # repo with the same branch name must not be attributed to this run.
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="main",
        )
        result = find_task_run(branch="main", repository="ArkeroAI/arkero2")
        self.assertIsNone(result)

    def test_branch_fallback_matches_repository_case_insensitively(self):
        task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="feature/my-branch",
        )
        result = find_task_run(branch="feature/my-branch", repository="PostHog/PostHog")
        self.assertEqual(result, task_run)

    def test_branch_fallback_rejects_empty_repository(self):
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            branch="main",
        )
        for value in ("", "   ", "\t"):
            self.assertIsNone(find_task_run(branch="main", repository=value))
