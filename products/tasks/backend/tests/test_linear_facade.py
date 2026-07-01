from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team
from posthog.models.integration import Integration, LinearAgentIntegration
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import Task, TaskExternalReference, TaskRun

ISSUE_UUID = "issue-uuid-1"
ISSUE_URL = "https://linear.app/acme/issue/ENG-1"


class TestLinearFacade(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Team")
        cls.user = User.objects.create(email="linear-facade@test.com", distinct_id="linear-facade")

    def _make_task(self, origin=Task.OriginProduct.LINEAR) -> Task:
        return Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin,
            created_by=self.user,
        )

    def test_create_task_external_reference_is_idempotent_per_issue(self):
        task = self._make_task()

        facade.create_task_external_reference(
            team_id=self.team.id, task_id=task.id, kind="linear-issue", external_id=ISSUE_UUID, external_url=ISSUE_URL
        )
        facade.create_task_external_reference(
            team_id=self.team.id, task_id=task.id, kind="linear-issue", external_id=ISSUE_UUID, external_url=ISSUE_URL
        )

        rows = TaskExternalReference.objects.for_team(self.team.id).filter(kind="linear-issue", external_id=ISSUE_UUID)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(
            facade.get_task_id_for_external_reference(
                team_id=self.team.id, kind="linear-issue", external_id=ISSUE_UUID
            ),
            task.id,
        )

    def test_get_task_id_for_external_reference_returns_none_when_absent(self):
        self.assertIsNone(
            facade.get_task_id_for_external_reference(team_id=self.team.id, kind="linear-issue", external_id="nope")
        )

    def test_linear_origin_run_with_pr_comments_on_issue(self):
        task = self._make_task(origin=Task.OriginProduct.LINEAR)
        run = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.COMPLETED, output={"pr_url": "https://gh/pr/7"}
        )
        Integration.objects.create(
            team=self.team,
            kind="linear-agent",
            integration_id="org-1",
            config={"data": {"viewer": {"id": "bot", "organization": {"id": "org-1"}}}},
            sensitive_config={"access_token": "tok"},
        )
        facade.create_task_external_reference(
            team_id=self.team.id, task_id=task.id, kind="linear-issue", external_id=ISSUE_UUID, external_url=ISSUE_URL
        )

        with patch.object(LinearAgentIntegration, "create_comment", return_value="c1") as mock_comment:
            facade._post_linear_update_for_pr(run)

        mock_comment.assert_called_once()
        self.assertEqual(mock_comment.call_args.kwargs["issue_id"], ISSUE_UUID)
        self.assertIn("https://gh/pr/7", mock_comment.call_args.kwargs["body"])

    def test_non_linear_origin_run_does_not_comment(self):
        task = self._make_task(origin=Task.OriginProduct.USER_CREATED)
        run = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.COMPLETED, output={"pr_url": "https://gh/pr/7"}
        )

        with patch.object(LinearAgentIntegration, "create_comment") as mock_comment:
            facade._post_linear_update_for_pr(run)

        mock_comment.assert_not_called()
