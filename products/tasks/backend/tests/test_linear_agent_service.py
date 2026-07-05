from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Integration, Organization, Team
from posthog.models.user import User

from products.tasks.backend.logic.linear_agent.client import LinearAgentApiError
from products.tasks.backend.logic.linear_agent.parsing import parse_agent_trigger
from products.tasks.backend.logic.linear_agent.service import (
    RECONNECT_INTEGRATION_MESSAGE,
    WORKFLOW_START_FAILED_MESSAGE,
    _resolve_repository,
    handle_linear_agent_event,
)
from products.tasks.backend.models import LinearIssueTaskMapping, Task
from products.tasks.backend.tests.test_linear_agent_webhooks import agent_session_payload, notification_payload

LINEAR_ORG_ID = "lin-org-1"


def flag_gate(enabled: bool):
    return patch(
        "posthoganalytics.feature_enabled",
        side_effect=lambda key, *args, **kwargs: enabled and key == "posthog-bot-everywhere",
    )


class LinearAgentServiceTestBase(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="installer@test.com", distinct_id="installer-distinct")
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="linear-agent",
            integration_id=LINEAR_ORG_ID,
            config={
                "data.viewer.id": "bot-user-1",
                "data.viewer.organization.id": LINEAR_ORG_ID,
                "data.viewer.organization.name": "Acme",
            },
            sensitive_config={"access_token": "linear-token"},
            created_by=cls.user,
        )
        Integration.objects.create(team=cls.team, kind="github", config={})

    def setUp(self):
        patches = {
            "flag": flag_gate(True),
            "repo": patch(
                "products.tasks.backend.logic.linear_agent.service._resolve_repository", return_value="posthog/posthog"
            ),
            "workflow": patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
            "comment": patch("products.tasks.backend.logic.linear_agent.client.LinearAgentClient.create_comment"),
            "activity": patch(
                "products.tasks.backend.logic.linear_agent.client.LinearAgentClient.create_agent_activity"
            ),
            "description": patch(
                "products.tasks.backend.logic.linear_agent.client.LinearAgentClient.get_issue_description",
                return_value="Fetched issue description",
            ),
        }
        mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        self.mock_repo = mocks["repo"]
        self.mock_workflow = mocks["workflow"]
        self.mock_comment = mocks["comment"]
        self.mock_activity = mocks["activity"]
        self.mock_get_description = mocks["description"]

    def _mappings(self):
        return LinearIssueTaskMapping.objects.for_team(self.team.id)


class TestHandleLinearAgentEvent(LinearAgentServiceTestBase):
    def test_assignment_creates_task_mapping_workflow_and_ack(self):
        handle_linear_agent_event(notification_payload())

        task = Task.objects.get(team=self.team, origin_product=Task.OriginProduct.LINEAR)
        self.assertEqual(task.created_by, self.user)
        self.assertEqual(task.repository, "posthog/posthog")
        self.assertEqual(task.title, "ENG-42: Fix the thing")
        # Description absent from the notification payload → fetched from Linear.
        self.assertIn("Fetched issue description", task.description)
        self.assertIn("https://linear.app/acme/issue/ENG-42/fix-the-thing", task.description)

        run = task.latest_run
        assert run is not None
        mapping = self._mappings().get(linear_issue_id="issue-uuid-1")
        self.assertEqual(mapping.task_id, task.id)
        self.assertEqual(mapping.task_run_id, run.id)
        self.assertEqual(mapping.integration_id, self.integration.id)
        self.assertEqual(mapping.linear_issue_identifier, "ENG-42")
        self.assertIsNone(mapping.linear_agent_session_id)

        self.mock_workflow.assert_called_once()
        self.assertEqual(self.mock_workflow.call_args.kwargs["run_id"], str(run.id))
        self.mock_comment.assert_called_once()
        issue_id, body = self.mock_comment.call_args.args
        self.assertEqual(issue_id, "issue-uuid-1")
        self.assertIn(f"/project/{self.team.id}/tasks/{task.id}", body)
        self.assertIn("posthog/posthog", body)

    def test_agent_session_event_acks_session_and_records_session_id(self):
        handle_linear_agent_event(agent_session_payload())

        self.mock_activity.assert_called_once()
        mapping = self._mappings().get(linear_issue_id="issue-uuid-2")
        self.assertEqual(mapping.linear_agent_session_id, "session-1")

    def test_unknown_organization_is_noop(self):
        handle_linear_agent_event(notification_payload(organization_id="other-org"))

        self.assertFalse(Task.objects.filter(team=self.team).exists())
        self.mock_comment.assert_not_called()

    def test_flag_off_creates_nothing(self):
        with flag_gate(False):
            handle_linear_agent_event(notification_payload())

        self.assertFalse(Task.objects.filter(team=self.team).exists())
        self.mock_comment.assert_not_called()

    def test_duplicate_issue_creates_single_task(self):
        handle_linear_agent_event(notification_payload())
        handle_linear_agent_event(notification_payload())

        self.assertEqual(Task.objects.filter(team=self.team).count(), 1)
        self.assertEqual(self._mappings().count(), 1)

    def test_mention_on_tracked_issue_points_to_existing_task(self):
        handle_linear_agent_event(notification_payload())
        task = Task.objects.get(team=self.team)
        self.mock_comment.reset_mock()

        handle_linear_agent_event(notification_payload(action="issueCommentMention"))

        self.assertEqual(Task.objects.filter(team=self.team).count(), 1)
        self.mock_comment.assert_called_once()
        _issue_id, body = self.mock_comment.call_args.args
        self.assertIn(str(task.id), body)

    def test_missing_installer_posts_reconnect_comment(self):
        Integration.objects.filter(id=self.integration.id).update(created_by=None)

        handle_linear_agent_event(notification_payload())

        self.assertFalse(Task.objects.filter(team=self.team).exists())
        self.mock_comment.assert_called_once()
        _issue_id, body = self.mock_comment.call_args.args
        self.assertEqual(body, RECONNECT_INTEGRATION_MESSAGE)

    def test_task_creation_failure_posts_error_comment(self):
        # A repository but no GitHub integration makes Task.create_and_run raise — the real
        # misconfiguration path, no internal mocking needed.
        Integration.objects.filter(team=self.team, kind="github").delete()
        self.mock_repo.return_value = "acme/private-repo"

        handle_linear_agent_event(notification_payload())

        self.assertFalse(Task.objects.filter(team=self.team).exists())
        self.assertFalse(self._mappings().exists())
        self.mock_comment.assert_called_once()

    def test_workflow_start_failure_unmaps_issue_so_retrigger_works(self):
        self.mock_workflow.side_effect = RuntimeError("temporal down")

        handle_linear_agent_event(notification_payload())

        self.assertFalse(self._mappings().exists())
        self.mock_comment.assert_called_once()
        _issue_id, body = self.mock_comment.call_args.args
        self.assertEqual(body, WORKFLOW_START_FAILED_MESSAGE)

        # Reassigning the issue must start fresh now that the mapping is gone.
        self.mock_workflow.side_effect = None
        handle_linear_agent_event(notification_payload())
        self.assertEqual(Task.objects.filter(team=self.team).count(), 2)
        self.assertEqual(self._mappings().count(), 1)

    def test_ack_comment_failure_does_not_lose_the_task(self):
        self.mock_comment.side_effect = LinearAgentApiError("linear down")

        handle_linear_agent_event(notification_payload())

        self.assertEqual(Task.objects.filter(team=self.team).count(), 1)
        self.mock_workflow.assert_called_once()


STUB_GITHUB = object()


class TestResolveRepository(LinearAgentServiceTestBase):
    CANDIDATES_MULTI = ["posthog/posthog", "posthog/posthog-js"]

    def _resolve(self, candidates, description=None, github=STUB_GITHUB):
        trigger = parse_agent_trigger(notification_payload())
        assert trigger is not None
        with (
            patch(
                "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration",
                return_value=github,
            ),
            patch(
                "products.tasks.backend.logic.repo_selection.agent.list_candidate_repos",
                return_value=candidates,
            ),
        ):
            return _resolve_repository(self.team, self.user.id, trigger, description)

    def test_explicit_repo_in_issue_text_wins(self):
        result = self._resolve(self.CANDIDATES_MULTI, description="Please fix posthog/posthog-js this week")
        self.assertEqual(result, "posthog/posthog-js")

    def test_single_candidate_short_circuits(self):
        self.assertEqual(self._resolve(["posthog/posthog"]), "posthog/posthog")

    @parameterized.expand(
        [
            ("ambiguous_multi_candidate", CANDIDATES_MULTI),
            ("no_candidates", []),
        ]
    )
    def test_unresolvable_returns_none(self, _name, candidates):
        self.assertIsNone(self._resolve(candidates))

    def test_no_github_integration_returns_none(self):
        self.assertIsNone(self._resolve(self.CANDIDATES_MULTI, github=None))

    def test_resolution_failure_degrades_to_none(self):
        trigger = parse_agent_trigger(notification_payload())
        assert trigger is not None
        with patch(
            "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration",
            side_effect=RuntimeError("github down"),
        ):
            self.assertIsNone(_resolve_repository(self.team, self.user.id, trigger, None))
