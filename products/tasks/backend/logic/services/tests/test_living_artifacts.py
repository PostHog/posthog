import io
import json
import zipfile
from typing import Any, ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.logic.services.living_artifacts import (
    DEFAULT_DOCUMENT_CONTENT_TYPE,
    ArtifactCommit,
    create_living_artifact,
    edit_living_artifact,
    register_s3_manifest_artifact,
)
from products.tasks.backend.models import Task, TaskArtifact, TaskRun


def _xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


class FakeDocumentConnectorAdapter:
    adapter = TaskArtifact.Adapter.DOCUMENT_CONNECTOR

    def open(self, artifact: TaskArtifact) -> str | None:
        return (artifact.versions or [])[-1].get("content") if artifact.versions else None

    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        document_id = (artifact.location or {}).get("document_id") if artifact is not None else artifact_id
        location = {
            "kind": "document_connector",
            "provider": "google_drive",
            "document_id": document_id,
            "url": f"https://docs.example.com/document/{document_id}",
        }
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={"document_connector_provider": "google_drive"},
            version={
                "version": version,
                "run_id": str(run.id),
                "adapter": self.adapter,
                "location": location,
                "content_type": content_type or DEFAULT_DOCUMENT_CONTENT_TYPE,
                "content": content,
            },
        )


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
        self.assertEqual(artifact.versions[0]["document_connector_fallback_reason"], "no_user_connector")
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        updated = edit_living_artifact(artifact=artifact, content="# Updated report")

        self.assertEqual(updated.current_version, 2)
        self.assertEqual(updated.adapter, TaskArtifact.Adapter.DOCUMENT_CONNECTOR)
        self.assertEqual([version["version"] for version in updated.versions], [1, 2])
        self.assertEqual(mock_write.call_count, 2)

    @patch("posthog.storage.object_storage.write")
    @patch("products.tasks.backend.logic.services.living_artifacts._document_connector_adapter_for_run")
    def test_document_adapter_uses_user_connector_when_available(self, mock_connector_for_run, mock_write):
        mock_connector_for_run.return_value = FakeDocumentConnectorAdapter()

        artifact = create_living_artifact(
            run=self.task_run,
            name="user_activity_report.md",
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            content="# Report",
        )

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.DOCUMENT_CONNECTOR)
        self.assertEqual(artifact.location["kind"], "document_connector")
        self.assertEqual(artifact.location["provider"], "google_drive")
        self.assertEqual(artifact.metadata["document_connector_status"], "connected")
        self.assertEqual(artifact.metadata["document_connector_provider"], "google_drive")
        mock_write.assert_not_called()

        updated = edit_living_artifact(artifact=artifact, content="# Updated report")

        self.assertEqual(updated.current_version, 2)
        self.assertEqual(updated.versions[-1]["document_connector_status"], "connected")
        self.assertEqual(updated.versions[-1]["content"], "# Updated report")
        self.assertEqual(updated.location["document_id"], artifact.location["document_id"])

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
        self.assertEqual(artifact.location["url"], "https://app.slack.com/docs/T123/F123")
        self.assertEqual(artifact.metadata["slack_canvas_url"], "https://app.slack.com/docs/T123/F123")
        self.assertEqual(updated.current_version, 2)
        self.assertEqual(updated.location["url"], "https://app.slack.com/docs/T123/F123")
        self.assertEqual(slack.api_call.call_args_list[0].args[0], "canvases.create")
        self.assertEqual(slack.api_call.call_args_list[1].args[0], "canvases.edit")
        edit_payload = slack.api_call.call_args_list[1].kwargs["json"]
        edit_change = edit_payload["changes"][0]
        self.assertEqual(edit_change["operation"], "replace")
        self.assertEqual(edit_change["document_content"]["markdown"], "# Updated report")
        slack.chat_postMessage.assert_called_once_with(
            channel="C123",
            thread_ts="1111.1",
            text="Created Slack canvas <https://app.slack.com/docs/T123/F123|Report canvas> (`F123`).",
            unfurl_links=False,
            unfurl_media=False,
        )
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

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_uploads_binary_versions(self, mock_integration_for_mapping, mock_post):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,files:write"},
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
        slack.api_call.side_effect = [
            {"upload_url": "https://files.slack.test/upload/1", "file_id": "F1"},
            {"files": [{"id": "F1", "title": "report.xlsx"}]},
            {"upload_url": "https://files.slack.test/upload/2", "file_id": "F2"},
            {"files": [{"id": "F2", "title": "report.xlsx"}]},
        ]
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration

        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        artifact = create_living_artifact(
            run=self.task_run,
            name="report.xlsx",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=b"first workbook",
            content_type=content_type,
        )
        updated = edit_living_artifact(
            artifact=artifact,
            content_bytes=b"second workbook",
            content_type=content_type,
        )

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.SLACK_FILE)
        self.assertEqual(artifact.location["kind"], "slack_file")
        self.assertEqual(artifact.location["file_id"], "F1")
        self.assertEqual(updated.location["file_id"], "F2")
        self.assertEqual(updated.current_version, 2)
        self.assertEqual([version["slack_file_id"] for version in updated.versions], ["F1", "F2"])
        self.assertEqual([version["size"] for version in updated.versions], [14, 15])
        self.assertEqual(slack.api_call.call_args_list[0].args[0], "files.getUploadURLExternal")
        self.assertEqual(slack.api_call.call_args_list[1].args[0], "files.completeUploadExternal")
        self.assertEqual(slack.api_call.call_args_list[2].args[0], "files.getUploadURLExternal")
        self.assertEqual(slack.api_call.call_args_list[3].args[0], "files.completeUploadExternal")
        self.assertEqual(mock_post.call_args_list[0].kwargs["data"], b"first workbook")
        self.assertEqual(mock_post.call_args_list[1].kwargs["data"], b"second workbook")
        complete_payload = slack.api_call.call_args_list[1].kwargs["data"]
        self.assertEqual(complete_payload["channel_id"], "C123")
        self.assertEqual(complete_payload["thread_ts"], "1111.1")
        slack_integration.missing_scopes.assert_called_with(frozenset({"files:write"}))
        self.assertEqual(mock_post.return_value.raise_for_status.call_count, 2)

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_presents_xlsx_payload_with_xlsx_filename(self, mock_integration_for_mapping, mock_post):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,files:write"},
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
        slack.api_call.side_effect = [
            {"upload_url": "https://files.slack.test/upload/1", "file_id": "F1"},
            {"files": [{"id": "F1", "title": "report.xlsx"}]},
        ]
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration

        artifact = create_living_artifact(
            run=self.task_run,
            name="report.zip",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=_xlsx_bytes(),
            content_type="application/zip",
        )

        self.assertEqual(artifact.name, "report.xlsx")
        self.assertEqual(
            artifact.versions[0]["content_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(
            artifact.location["content_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(slack.api_call.call_args_list[0].kwargs["data"]["filename"], "report.xlsx")
        complete_payload = slack.api_call.call_args_list[1].kwargs["data"]
        self.assertEqual(json.loads(complete_payload["files"])[0]["title"], "report.xlsx")
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @patch("posthog.storage.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_uploads_source_artifact(self, mock_integration_for_mapping, mock_post, mock_read_bytes):
        workbook_bytes = _xlsx_bytes()
        mock_read_bytes.return_value = workbook_bytes
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,files:write"},
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
        slack.api_call.side_effect = [
            {"upload_url": "https://files.slack.test/upload/1", "file_id": "F1"},
            {"files": [{"id": "F1", "title": "report.xlsx", "permalink": "https://slack.test/files/F1"}]},
        ]
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{self.task_run.id}/report.zip"
        self.task_run.artifacts = [
            {
                "id": "artifact-1",
                "name": "report.zip",
                "source": "agent_output",
                "size": len(workbook_bytes),
                "content_type": "application/zip",
                "storage_path": storage_path,
            }
        ]
        self.task_run.save(update_fields=["artifacts", "updated_at"])

        artifact = create_living_artifact(
            run=self.task_run,
            name="report.zip",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            source_artifact_id="artifact-1",
        )

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.SLACK_FILE)
        self.assertEqual(artifact.name, "report.xlsx")
        self.assertEqual(
            artifact.versions[0]["content_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(artifact.versions[0]["source_artifact_id"], "artifact-1")
        self.assertEqual(artifact.metadata["slack_file_permalink"], "https://slack.test/files/F1")
        mock_read_bytes.assert_called_once_with(storage_path, missing_ok=True)
        self.assertEqual(mock_post.call_args.kwargs["data"], workbook_bytes)
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_requires_file_scope(self, mock_integration_for_mapping):
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
        slack_integration.missing_scopes.return_value = {"files:write"}
        mock_integration_for_mapping.return_value = slack_integration

        with self.assertRaisesRegex(ValueError, "files:write"):
            create_living_artifact(
                run=self.task_run,
                name="report.xlsx",
                artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
                adapter=TaskArtifact.Adapter.SLACK_FILE,
                content_bytes=b"workbook",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
