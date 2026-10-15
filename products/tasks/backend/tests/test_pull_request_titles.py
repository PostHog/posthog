from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from posthog.models import Integration

from products.tasks.backend.logic.pull_request_titles import pull_request_titles
from products.tasks.backend.models import Task, TaskRun


class TestPullRequestTitles(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Example change",
            repository="example/repo",
            github_integration=integration,
        )
        TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status="completed",
            output={
                "pr_url": "https://github.com/example/repo/pull/1/files",
                "pr_urls": ["https://github.com/example/other/pull/2"],
            },
        )

    @patch(
        "products.tasks.backend.logic.pull_request_titles.GitHubIntegration.access_token_expired", return_value=False
    )
    @patch("products.tasks.backend.logic.pull_request_titles.GitHubIntegration._gh_graphql")
    def test_fetches_in_repository_titles_once(self, graphql, _expired):
        graphql.return_value = {"pr0": {"pullRequest": {"title": "Fix the example"}}}

        first = pull_request_titles(self.team.id, self.user.id, [self.task.id])
        second = pull_request_titles(self.team.id, self.user.id, [self.task.id])

        expected = {"https://github.com/example/repo/pull/1": "Fix the example"}
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        graphql.assert_called_once()
        self.assertEqual(graphql.call_args.args[1], {"owner0": "example", "repo0": "repo", "number0": 1})
