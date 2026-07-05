from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models import Integration, Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.linear_agent.client import LinearAgentApiError
from products.tasks.backend.linear_agent.sync import post_linear_update_for_run_impl
from products.tasks.backend.models import LinearIssueTaskMapping, Task, TaskRun

PR_URL = "https://github.com/posthog/posthog/pull/123"


class LinearAgentSyncTestBase(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="sync@test.com", distinct_id="sync-distinct")
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="linear-agent",
            integration_id="lin-org-1",
            config={"data.viewer.id": "bot-user-1"},
            sensitive_config={"access_token": "linear-token"},
            created_by=cls.user,
        )

    def _make_run(self, *, mapped: bool = True, agent_session_id: str | None = None, **run_kwargs) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Linear task",
            description="desc",
            origin_product=Task.OriginProduct.LINEAR,
            created_by=self.user,
            repository="posthog/posthog",
        )
        defaults = {"status": TaskRun.Status.IN_PROGRESS}
        defaults.update(run_kwargs)
        run = TaskRun.objects.create(task=task, team=self.team, **defaults)
        if mapped:
            LinearIssueTaskMapping.objects.for_team(self.team.id).create(
                team=self.team,
                integration=self.integration,
                linear_organization_id="lin-org-1",
                linear_issue_id="issue-uuid-1",
                linear_issue_identifier="ENG-42",
                linear_issue_url="https://linear.app/acme/issue/ENG-42",
                linear_agent_session_id=agent_session_id,
                task=task,
                task_run=run,
            )
        return run


class TestLinearUpdateDispatch(LinearAgentSyncTestBase):
    @patch("products.tasks.backend.tasks.post_linear_update_for_run")
    def test_new_pr_url_on_mapped_run_dispatches_update(self, mock_task):
        run = self._make_run()

        with self.captureOnCommitCallbacks(execute=True):
            facade.update_task_run(run.id, run.task_id, self.team.id, validated_data={"output": {"pr_url": PR_URL}})

        mock_task.delay.assert_called_once_with(run_id=str(run.id), kind="pr_opened", error_message=None)

    @patch("products.tasks.backend.tasks.post_linear_update_for_run")
    def test_unmapped_run_does_not_dispatch(self, mock_task):
        run = self._make_run(mapped=False)

        with self.captureOnCommitCallbacks(execute=True):
            facade.update_task_run(run.id, run.task_id, self.team.id, validated_data={"output": {"pr_url": PR_URL}})

        mock_task.delay.assert_not_called()

    @patch("products.tasks.backend.tasks.post_linear_update_for_run")
    def test_unchanged_pr_url_does_not_redispatch(self, mock_task):
        run = self._make_run(output={"pr_url": PR_URL})

        with self.captureOnCommitCallbacks(execute=True):
            facade.update_task_run(
                run.id, run.task_id, self.team.id, validated_data={"output": {"pr_url": PR_URL, "extra": "x"}}
            )

        mock_task.delay.assert_not_called()

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    @patch("products.tasks.backend.tasks.post_linear_update_for_run")
    def test_failed_transition_dispatches_failure_update(self, mock_task, _mock_signal):
        run = self._make_run()

        with self.captureOnCommitCallbacks(execute=True):
            facade.update_task_run(
                run.id,
                run.task_id,
                self.team.id,
                validated_data={"status": TaskRun.Status.FAILED, "error_message": "boom"},
            )

        mock_task.delay.assert_called_once_with(run_id=str(run.id), kind="failed", error_message="boom")

    @patch(
        "products.tasks.backend.linear_agent.sync.dispatch_linear_update_for_run",
        side_effect=RuntimeError("sync exploded"),
    )
    def test_dispatch_failure_never_breaks_update_task_run(self, _mock_dispatch):
        run = self._make_run()

        dto = facade.update_task_run(run.id, run.task_id, self.team.id, validated_data={"output": {"pr_url": PR_URL}})

        assert dto is not None
        self.assertEqual((dto.output or {}).get("pr_url"), PR_URL)

    @patch("products.tasks.backend.tasks.post_linear_update_for_run")
    def test_set_task_run_output_dispatches_update(self, mock_task):
        run = self._make_run()

        with self.captureOnCommitCallbacks(execute=True):
            facade.set_task_run_output(run.id, run.task_id, self.team.id, output={"pr_url": PR_URL})

        mock_task.delay.assert_called_once_with(run_id=str(run.id), kind="pr_opened", error_message=None)


class TestPostLinearUpdateForRun(LinearAgentSyncTestBase):
    def _graphql_response(self, body: dict) -> MagicMock:
        return MagicMock(status_code=200, json=MagicMock(return_value=body))

    @patch("products.tasks.backend.linear_agent.client.requests.post")
    def test_pr_opened_posts_comment_on_mapped_issue(self, mock_post):
        mock_post.return_value = self._graphql_response({"data": {"commentCreate": {"success": True}}})
        run = self._make_run(output={"pr_url": PR_URL})

        post_linear_update_for_run_impl(str(run.id), "pr_opened", None)

        mock_post.assert_called_once()
        request_json = mock_post.call_args.kwargs["json"]
        self.assertIn("commentCreate", request_json["query"])
        self.assertEqual(request_json["variables"]["issueId"], "issue-uuid-1")
        self.assertIn(PR_URL, request_json["variables"]["body"])

    @patch("products.tasks.backend.linear_agent.client.requests.post")
    def test_failed_run_posts_failure_comment_with_task_link(self, mock_post):
        mock_post.return_value = self._graphql_response({"data": {"commentCreate": {"success": True}}})
        run = self._make_run(status=TaskRun.Status.FAILED, error_message="agent crashed")

        post_linear_update_for_run_impl(str(run.id), "failed", None)

        body = mock_post.call_args.kwargs["json"]["variables"]["body"]
        self.assertIn("agent crashed", body)
        self.assertIn(f"/project/{self.team.id}/tasks/{run.task_id}", body)

    @patch("products.tasks.backend.linear_agent.client.requests.post")
    def test_agent_session_also_receives_activity(self, mock_post):
        mock_post.return_value = self._graphql_response({"data": {"ok": True}})
        run = self._make_run(agent_session_id="session-1", output={"pr_url": PR_URL})

        post_linear_update_for_run_impl(str(run.id), "pr_opened", None)

        self.assertEqual(mock_post.call_count, 2)
        activity_json = mock_post.call_args_list[1].kwargs["json"]
        self.assertIn("agentActivityCreate", activity_json["query"])
        self.assertEqual(activity_json["variables"]["input"]["agentSessionId"], "session-1")

    @patch("products.tasks.backend.linear_agent.client.requests.post")
    def test_graphql_error_raises_for_celery_retry(self, mock_post):
        mock_post.return_value = self._graphql_response({"errors": [{"message": "rate limited"}]})
        run = self._make_run(output={"pr_url": PR_URL})

        with self.assertRaises(LinearAgentApiError):
            post_linear_update_for_run_impl(str(run.id), "pr_opened", None)

    @patch("products.tasks.backend.linear_agent.client.requests.post")
    def test_missing_pr_url_or_mapping_is_noop(self, mock_post):
        run_without_pr = self._make_run()
        post_linear_update_for_run_impl(str(run_without_pr.id), "pr_opened", None)

        unmapped_run = self._make_run(mapped=False, output={"pr_url": PR_URL})
        post_linear_update_for_run_impl(str(unmapped_run.id), "pr_opened", None)

        mock_post.assert_not_called()
