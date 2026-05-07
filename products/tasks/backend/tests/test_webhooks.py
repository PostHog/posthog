import hmac
import json
import hashlib
from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.models import SignalReport, SignalReportTask
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
    def test_non_pr_non_issue_event_ignored(self, mock_get_secret):
        """Test that events other than pull_request/issues/issue_comment are acknowledged but ignored."""
        mock_get_secret.return_value = self.webhook_secret

        payload = {"action": "created", "ref": "refs/heads/main"}

        response = self._make_webhook_request(payload, event_type="push")

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


class TestGitHubPRWebhookResolvesSignalReports(TestCase):
    """Webhook resolves any SignalReport linked to the merged PR's task."""

    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="test@example.com", distinct_id="user-123")

    def setUp(self):
        self.client = APIClient()
        self.webhook_secret = "test-webhook-secret"
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Signal task",
            description="Implementation of a signal report",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            repository="posthog/posthog",
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/posthog/posthog/pull/42"},
        )
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
        )
        SignalReportTask.objects.create(
            team=self.team,
            report=self.report,
            task=self.task,
            relationship=SignalReportTask.Relationship.IMPLEMENTATION,
        )

    def _post_pr_webhook(self, action: str, merged: bool):
        payload = {
            "action": action,
            "pull_request": {
                "html_url": "https://github.com/posthog/posthog/pull/42",
                "merged": merged,
            },
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = generate_github_signature(payload_bytes, self.webhook_secret)
        return self.client.post(
            "/webhooks/github/pr/",
            data=payload_bytes,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
            HTTP_X_GITHUB_EVENT="pull_request",
        )

    @parameterized.expand(
        [
            (
                "merged_pr_resolves_ready_report",
                "closed",
                True,
                SignalReport.Status.READY,
                SignalReport.Status.RESOLVED,
            ),
            (
                "closed_without_merge_is_noop",
                "closed",
                False,
                SignalReport.Status.READY,
                SignalReport.Status.READY,
            ),
            (
                "suppressed_report_is_skipped",
                "closed",
                True,
                SignalReport.Status.SUPPRESSED,
                SignalReport.Status.SUPPRESSED,
            ),
        ]
    )
    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_pr_event_transitions_linked_report(
        self, _name, action, merged, initial_status, expected_status, _mock_capture, mock_get_secret
    ):
        mock_get_secret.return_value = self.webhook_secret
        if self.report.status != initial_status:
            self.report.status = initial_status
            self.report.save(update_fields=["status"])

        response = self._post_pr_webhook(action=action, merged=merged)

        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, expected_status)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_merge_on_task_without_linked_report_is_a_noop(self, _mock_capture, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret
        SignalReportTask.objects.filter(task=self.task).delete()

        response = self._post_pr_webhook(action="closed", merged=True)

        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, SignalReport.Status.READY)


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


class TestGitHubWebhookFanout(TestCase):
    """Verify that the unified ``github_webhook`` dispatcher routes events
    to the correct product handler. Tests both ``/webhooks/github/pr/``
    (legacy) and ``/webhooks/github/`` (new unified URL)."""

    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Fanout Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Fanout Team")
        cls.user = User.objects.create(email="fanout@example.com", distinct_id="fanout-1")
        cls.task = Task.objects.create(
            team=cls.team,
            created_by=cls.user,
            title="Fanout Task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="myorg/myrepo",
        )
        cls.task_run = TaskRun.objects.create(
            task=cls.task,
            team=cls.team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/myorg/myrepo/pull/99"},
        )
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="github",
            integration_id="77777",
            config={"account": {"name": "myorg"}},
        )
        cls.team.conversations_enabled = True
        cls.team.conversations_settings = {
            "github_enabled": True,
            "github_integration_id": cls.integration.id,
            "github_repos": ["myorg/myrepo"],
        }
        cls.team.save()

    def setUp(self):
        self.client = APIClient()
        self.webhook_secret = "test-webhook-secret"

    def _make_request(
        self, payload: dict, event_type: str = "issues", delivery_id: str = "del-1", url: str = "/webhooks/github/pr/"
    ):
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = generate_github_signature(payload_bytes, self.webhook_secret)
        return self.client.post(
            url,
            data=payload_bytes,
            content_type="application/json",
            headers={
                "x-hub-signature-256": signature,
                "x-github-event": event_type,
                "x-github-delivery": delivery_id,
            },
        )

    @parameterized.expand(
        [
            ("legacy_url", "/webhooks/github/pr/"),
            ("unified_url", "/webhooks/github/"),
        ]
    )
    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_issues_event_dispatched_to_conversations(self, _name, url, mock_secret, mock_task):
        mock_secret.return_value = self.webhook_secret
        mock_task.delay = MagicMock()

        payload = {
            "action": "opened",
            "installation": {"id": 77777},
            "repository": {"full_name": "myorg/myrepo"},
            "issue": {"number": 42, "title": "Bug", "body": "", "user": {"login": "dev"}},
            "sender": {"login": "dev"},
        }

        response = self._make_request(payload, event_type="issues", url=url)

        self.assertEqual(response.status_code, 202)
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        self.assertEqual(call_kwargs["event_type"], "issues")
        self.assertEqual(call_kwargs["team_id"], self.team.id)
        self.assertEqual(call_kwargs["repo"], "myorg/myrepo")

    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_issue_comment_event_dispatched_to_conversations(self, mock_secret, mock_task):
        mock_secret.return_value = self.webhook_secret
        mock_task.delay = MagicMock()

        payload = {
            "action": "created",
            "installation": {"id": 77777},
            "repository": {"full_name": "myorg/myrepo"},
            "issue": {"number": 42, "title": "Bug", "body": "", "user": {"login": "dev"}},
            "comment": {"id": 999, "body": "Looks good", "user": {"login": "reviewer"}},
            "sender": {"login": "reviewer"},
        }

        response = self._make_request(payload, event_type="issue_comment")

        self.assertEqual(response.status_code, 202)
        mock_task.delay.assert_called_once()
        self.assertEqual(mock_task.delay.call_args[1]["event_type"], "issue_comment")

    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_issues_event_without_matching_team_returns_200(self, mock_secret, mock_task):
        mock_secret.return_value = self.webhook_secret
        mock_task.delay = MagicMock()

        payload = {
            "action": "opened",
            "installation": {"id": 99999},
            "repository": {"full_name": "other/repo"},
            "issue": {"number": 1, "title": "X", "body": "", "user": {"login": "u"}},
            "sender": {"login": "u"},
        }

        response = self._make_request(payload, event_type="issues")

        self.assertEqual(response.status_code, 200)
        mock_task.delay.assert_not_called()

    @parameterized.expand(
        [
            ("legacy_url", "/webhooks/github/pr/"),
            ("unified_url", "/webhooks/github/"),
        ]
    )
    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_pull_request_routed(self, _name, url, mock_capture, mock_secret):
        mock_secret.return_value = self.webhook_secret

        payload = {
            "action": "closed",
            "pull_request": {
                "html_url": "https://github.com/myorg/myrepo/pull/99",
                "merged": True,
            },
        }

        response = self._make_request(payload, event_type="pull_request", url=url)

        self.assertEqual(response.status_code, 200)
        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args[1]["event"], "pr_merged")

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_unified_url_unknown_event_returns_200(self, mock_secret):
        mock_secret.return_value = self.webhook_secret

        payload = {"action": "created", "ref": "refs/heads/main"}
        response = self._make_request(payload, event_type="push", url="/webhooks/github/")

        self.assertEqual(response.status_code, 200)

    @patch("products.tasks.backend.webhooks.get_github_webhook_secret")
    def test_unified_url_bad_signature_returns_403(self, mock_secret):
        mock_secret.return_value = self.webhook_secret

        payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
        response = self.client.post(
            "/webhooks/github/",
            data=payload_bytes,
            content_type="application/json",
            headers={
                "x-hub-signature-256": "sha256=invalid",
                "x-github-event": "issues",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_unified_url_get_returns_405(self):
        response = self.client.get("/webhooks/github/")
        self.assertEqual(response.status_code, 405)
