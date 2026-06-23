from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.logic.services.living_artifacts import (
    create_living_artifact,
    edit_living_artifact,
    register_s3_manifest_artifact,
)
from products.tasks.backend.models import Task, TaskArtifact, TaskRun


class TestLivingArtifacts(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="artifact@example.com", distinct_id="artifact-user")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Artifact task",
            description="Build a report",
            origin_product=Task.OriginProduct.SLACK,
            task_kind=Task.TaskKind.GENERAL,
            created_by=cls.user,
        )
        cls.task_run = TaskRun.objects.create(task=cls.task, team=cls.team, status=TaskRun.Status.IN_PROGRESS)

    @patch("posthog.storage.object_storage.read", return_value="# Report")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_document_adapter_records_s3_fallback_versions(self, mock_write, mock_tag, _mock_read):
        artifact = create_living_artifact(
            run=self.task_run,
            name="user_activity_report.md",
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            content="# Report",
        )

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.DOCUMENT_CONNECTOR)
        self.assertEqual(artifact.location["kind"], "s3")
        self.assertEqual(artifact.current_version, 1)
        self.assertEqual(artifact.versions[0]["version"], 1)
        self.assertEqual(artifact.versions[0]["document_connector_status"], "fallback_s3")
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        updated = edit_living_artifact(artifact=artifact, content="# Updated report")

        self.assertEqual(updated.current_version, 2)
        self.assertEqual(updated.adapter, TaskArtifact.Adapter.DOCUMENT_CONNECTOR)
        self.assertEqual([version["version"] for version in updated.versions], [1, 2])
        self.assertEqual(mock_write.call_count, 2)

    def test_register_s3_manifest_artifact_is_idempotent(self):
        entry = {
            "id": "artifact-1",
            "name": "plan.md",
            "type": "artifact",
            "source": "agent_output",
            "size": 10,
            "content_type": "text/markdown",
            "storage_path": "tasks/artifacts/team_1/task_1/run_1/plan.md",
            "uploaded_at": "2026-06-23T00:00:00Z",
        }

        first = register_s3_manifest_artifact(self.task_run, entry)
        second = register_s3_manifest_artifact(self.task_run, {**entry, "name": "renamed.md"})

        self.assertEqual(first.id, second.id)
        self.assertEqual(TaskArtifact.objects.for_team(self.team.id).count(), 1)
        second.refresh_from_db()
        self.assertEqual(second.name, "renamed.md")
        self.assertEqual(second.metadata["source_artifact_id"], "artifact-1")

    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_canvas_adapter_creates_and_edits_canvas(self, mock_integration_for_mapping):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,canvases:write"},
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U123",
        )
        slack = MagicMock()
        slack.api_call.return_value = {"canvas_id": "F123"}
        slack.chat_postMessage.return_value = {"ts": "1111.2"}
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration

        artifact = create_living_artifact(
            run=self.task_run,
            name="Report canvas",
            artifact_type=TaskArtifact.ArtifactType.SLACK_CANVAS,
            content="# Report",
        )
        updated = edit_living_artifact(artifact=artifact, content="# Updated report")

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.SLACK_CANVAS)
        self.assertEqual(artifact.location["canvas_id"], "F123")
        self.assertEqual(updated.current_version, 2)
        self.assertEqual(slack.api_call.call_args_list[0].args[0], "canvases.create")
        self.assertEqual(slack.api_call.call_args_list[1].args[0], "canvases.edit")
        slack_integration.missing_scopes.assert_called()

    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_canvas_adapter_requires_canvas_scope(self, mock_integration_for_mapping):
        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T123", config={})
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U123",
        )
        slack_integration = MagicMock()
        slack_integration.missing_scopes.return_value = {"canvases:write"}
        mock_integration_for_mapping.return_value = slack_integration

        with self.assertRaisesRegex(ValueError, "canvases:write"):
            create_living_artifact(
                run=self.task_run,
                name="Report canvas",
                artifact_type=TaskArtifact.ArtifactType.SLACK_CANVAS,
                content="# Report",
            )
