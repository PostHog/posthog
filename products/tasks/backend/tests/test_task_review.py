from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from posthog.models import Integration

from products.tasks.backend.logic.task_review import task_review
from products.tasks.backend.models import Task, TaskRun


class TestTaskReview(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Example change",
            repository="example/repo",
            github_integration=self.integration,
        )
        self.run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status="completed",
            output={"pr_url": "https://github.com/example/repo/pull/1"},
        )

    def test_owner_and_repository_are_required(self):
        with self.assertRaises(NotFound):
            task_review(self.team.id, str(self.task.id), self.user.id + 1, 1)
        self.run.output = {"pr_url": "https://github.com/example/other/pull/1"}
        self.run.save()
        with self.assertRaises(PermissionDenied):
            task_review(self.team.id, str(self.task.id), self.user.id, 1)

    def test_does_not_fall_back_to_unrelated_integration(self):
        self.task.github_integration = None
        self.task.save()
        with self.assertRaises(ValidationError):
            task_review(self.team.id, str(self.task.id), self.user.id, 1)

    @patch("products.tasks.backend.logic.task_review.GitHubIntegration.api_request")
    @patch("products.tasks.backend.logic.task_review.GitHubIntegration.get_pull_request_snapshot")
    @patch("products.tasks.backend.logic.task_review.GitHubIntegration.access_token_expired", return_value=False)
    def test_diff_limit_and_pagination(self, _expired, snapshot, request):
        snapshot.return_value = {
            "success": True,
            "title": "Example change",
            "state": "open",
            "ci_status": "success",
            "head_sha": "abc",
        }
        request.return_value = MagicMock(
            status_code=200, headers={"Link": '<https://api.github.com/files?page=2>; rel="next"'}
        )
        request.return_value.json.return_value = [
            {"filename": "example.ts", "status": "modified", "additions": 3, "deletions": 1, "patch": "+" * 20001}
        ]
        result = task_review(self.team.id, str(self.task.id), self.user.id, 1)
        self.assertEqual(len(result["files"][0]["patch"]), 20000)
        self.assertTrue(result["files"][0]["truncated"])
        self.assertTrue(result["has_more"])
        self.assertEqual(request.call_args.kwargs["params"], {"per_page": 30, "page": 1})

    def test_review_endpoint_rejects_invalid_pagination(self):
        response = self.client.get(f"/api/projects/{self.team.id}/tasks/{self.task.id}/review/", {"page": 0})
        self.assertEqual(response.status_code, 400)
