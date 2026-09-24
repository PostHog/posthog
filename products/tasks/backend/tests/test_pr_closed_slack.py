from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import RunFooter
from products.slack_app.backend.slack_thread import SlackThreadHandler
from products.tasks.backend.logic.services.pr_closed_slack import post_pr_closed_slack_update
from products.tasks.backend.models import SLACK_NOTIFIED_PR_URL_STATE_KEY, Task, TaskRun

PR_URL = "https://github.com/posthog/posthog/pull/1"
OTHER_PR_URL = "https://github.com/posthog/posthog/pull/2"


class TestPostPrClosedSlackUpdate(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=organization, name="Team")
        user = User.objects.create(email="pr-closed@example.com", distinct_id="pr-closed-user")
        self.task = Task.objects.create(
            team=self.team,
            created_by=user,
            title="Task",
            description="",
            origin_product=Task.OriginProduct.SLACK,
            state={SLACK_NOTIFIED_PR_URL_STATE_KEY: PR_URL},
        )
        self.run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"slack_actor_slack_user_id": "U_ACTOR"},
        )
        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        self.mapping_kwargs = {
            "team": self.team,
            "integration": integration,
            "slack_workspace_id": "T_SLACK",
            "channel": "C001",
            "thread_ts": "1234.5678",
            "task": self.task,
            "task_run": self.run,
            "mentioning_slack_user_id": "U_MENTIONER",
        }
        footer_patcher = patch(
            "products.tasks.backend.logic.services.pr_closed_slack.load_run_footer",
            return_value=RunFooter(task_url="http://localhost:8000/project/1/tasks/1"),
        )
        footer_patcher.start()
        self.addCleanup(footer_patcher.stop)

    @parameterized.expand(
        [
            ("announced_pr", PR_URL, True, [1, 0]),
            ("pr_the_thread_never_announced", OTHER_PR_URL, True, [0, 0]),
            ("task_without_slack_thread", PR_URL, False, [0, 0]),
        ]
    )
    @patch.object(SlackThreadHandler, "post_pr_closed")
    def test_posts_once_per_announced_pr(self, _name, closed_pr_url, has_mapping, expected_posts, mock_post):
        if has_mapping:
            SlackThreadTaskMapping.objects.create(**self.mapping_kwargs)

        posts = []
        for _ in range(2):
            mock_post.reset_mock()
            post_pr_closed_slack_update(str(self.run.id), closed_pr_url)
            posts.append(mock_post.call_count)

        assert posts == expected_posts

    @patch.object(SlackThreadHandler, "post_pr_closed")
    def test_tags_the_run_actor(self, mock_post):
        SlackThreadTaskMapping.objects.create(**self.mapping_kwargs)

        post_pr_closed_slack_update(str(self.run.id), PR_URL)

        mock_post.assert_called_once_with(
            PR_URL, "http://localhost:8000/project/1/tasks/1", reply_target_slack_user_id="U_ACTOR"
        )
