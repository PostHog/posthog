import io
import zipfile
from typing import Any, ClassVar

from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.db.models.query import QuerySet
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.facade.api import set_task_run_output, update_task_run
from products.tasks.backend.logic.services.living_artifacts import (
    DEFAULT_DOCUMENT_CONTENT_TYPE,
    ArtifactCommit,
    DocumentConnectorUnavailable,
    create_living_artifact,
    deliver_pending_slack_file_artifacts,
    edit_living_artifact,
    get_task_artifact_for_run,
    get_task_artifacts_for_run,
    record_github_pr_artifact,
)
from products.tasks.backend.models import Channel, Task, TaskArtifact, TaskRun


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

    def setUp(self) -> None:
        artifacts_flag = patch(
            "products.slack_app.backend.feature_flags.is_slack_app_living_artifacts_enabled",
            return_value=True,
        )
        artifacts_flag.start()
        self.addCleanup(artifacts_flag.stop)

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
            created_by=cls.user,
        )
        cls.task_run = TaskRun.objects.create(task=cls.task, team=cls.team, status=TaskRun.Status.IN_PROGRESS)

    @patch("posthog.storage.object_storage.write")
    def test_document_adapter_requires_external_connector(self, mock_write):
        with self.assertRaisesRegex(DocumentConnectorUnavailable, "No external document connector"):
            create_living_artifact(
                run=self.task_run,
                name="user_activity_report.md",
                artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
                content="# Report",
            )

        mock_write.assert_not_called()

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

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_mapped_slack_document_defaults_to_canvas_external_pointer(self, mock_integration_for_mapping, _mock_flag):
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
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
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

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_follow_up_run_sees_and_edits_prior_run_artifacts(self, mock_integration_for_mapping, _mock_flag):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,canvases:write"},
        )
        mapping = SlackThreadTaskMapping.objects.create(
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
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            content="# Report",
        )

        # A Slack follow-up resumes the task on a new run and repoints the thread mapping to it.
        follow_up_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"resume_from_run_id": str(self.task_run.id)},
        )
        mapping.task_run = follow_up_run
        mapping.save(update_fields=["task_run"])

        self.assertEqual([a.id for a in get_task_artifacts_for_run(follow_up_run)], [artifact.id])
        fetched = get_task_artifact_for_run(follow_up_run, artifact.id)
        assert fetched is not None

        updated = edit_living_artifact(artifact=fetched, run=follow_up_run, content="# Updated report")

        self.assertEqual(updated.current_version, 2)
        self.assertEqual(slack.api_call.call_args_list[-1].args[0], "canvases.edit")

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_canvas_adapter_requires_canvas_scope(self, mock_integration_for_mapping, _mock_flag):
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

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_stores_binary_versions_until_relay(
        self, mock_integration_for_mapping, mock_write, mock_tag, _mock_flag
    ):
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
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration

        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        artifact = create_living_artifact(
            run=self.task_run,
            name="report.xlsx",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
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
        self.assertEqual(artifact.location["delivery_status"], "pending")
        self.assertNotIn("file_id", artifact.location)
        self.assertEqual(updated.location["delivery_status"], "pending")
        self.assertNotIn("file_id", updated.location)
        self.assertEqual(updated.current_version, 2)
        self.assertEqual([version["delivery_status"] for version in updated.versions], ["pending", "pending"])
        self.assertEqual([version["size"] for version in updated.versions], [14, 15])
        self.assertEqual(mock_write.call_args_list[0].args[1], b"first workbook")
        self.assertEqual(mock_write.call_args_list[1].args[1], b"second workbook")
        self.assertEqual(mock_write.call_args_list[0].args[2], {"ContentType": content_type})
        self.assertEqual(mock_write.call_args_list[1].args[2], {"ContentType": content_type})
        self.assertEqual(mock_tag.call_count, 2)
        slack.api_call.assert_not_called()
        slack_integration.missing_scopes.assert_called_with(frozenset({"files:write"}))

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_presents_xlsx_payload_with_xlsx_filename(
        self, mock_integration_for_mapping, mock_write, _mock_tag, _mock_flag
    ):
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
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration

        workbook_bytes = _xlsx_bytes()
        artifact = create_living_artifact(
            run=self.task_run,
            name="report.zip",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=workbook_bytes,
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
        self.assertIn("report.v1.xlsx", artifact.location["storage_path"])
        self.assertEqual(mock_write.call_args.args[1], workbook_bytes)
        self.assertEqual(mock_write.call_args.args[2]["ContentType"], artifact.location["content_type"])
        slack.api_call.assert_not_called()

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_stores_source_artifact_until_relay(
        self, mock_integration_for_mapping, mock_read_bytes, mock_write, _mock_tag, _mock_flag
    ):
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
        slack_integration = MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{self.task_run.id}/report.zip"
        self.task_run.artifacts = [
            {
                "id": "artifact-1",
                "name": "report.zip",
                "type": "output",
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
        self.assertEqual(artifact.metadata["delivery_status"], "pending")
        self.assertNotIn("slack_file_permalink", artifact.metadata)
        mock_read_bytes.assert_called_once_with(storage_path, missing_ok=True)
        self.assertEqual(mock_write.call_args.args[1], workbook_bytes)
        self.assertEqual(
            mock_write.call_args.args[2]["ContentType"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        slack.api_call.assert_not_called()

    @parameterized.expand(
        [
            ("internal_type_by_id", "tree_snapshot", "agent_output", "id"),
            ("user_attachment_by_id", "user_attachment", "user_attachment", "id"),
            ("unlabeled_source_by_id", "output", "", "id"),
            ("internal_type_by_storage_path", "tree_snapshot", "agent_output", "storage_path"),
        ]
    )
    def test_internal_run_artifacts_rejected_as_living_artifact_sources(
        self, _name: str, entry_type: str, entry_source: str, reference_by: str
    ) -> None:
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{self.task_run.id}/state.bin"
        self.task_run.artifacts = [
            {
                "id": "artifact-1",
                "name": "state.bin",
                "type": entry_type,
                "source": entry_source,
                "size": 4,
                "content_type": "application/octet-stream",
                "storage_path": storage_path,
            }
        ]
        self.task_run.save(update_fields=["artifacts", "updated_at"])
        source_artifact_id = "artifact-1" if reference_by == "id" else None
        source_storage_path = storage_path if reference_by == "storage_path" else None

        with self.assertRaisesRegex(ValueError, "not a shareable run output"):
            create_living_artifact(
                run=self.task_run,
                name="state.bin",
                artifact_type=TaskArtifact.ArtifactType.FILE,
                adapter=TaskArtifact.Adapter.SLACK_FILE,
                source_artifact_id=source_artifact_id,
                source_storage_path=source_storage_path,
            )

        self.assertFalse(TaskArtifact.objects.for_team(self.team.id).exists())

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_requires_file_scope(self, mock_integration_for_mapping, _mock_flag):
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

    def _create_mapping_with_full_scopes(self) -> None:
        # Scopes granted (the DEV-install shape) so these tests prove the feature flag
        # gates canvas/file delivery even where the in-review scopes are available.
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,canvases:write,files:write"},
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

    @patch(
        "products.slack_app.backend.feature_flags.is_slack_app_living_artifacts_enabled",
        return_value=False,
    )
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_living_artifact_creation_rejected_when_flag_off(
        self, mock_integration_for_mapping, _mock_flag
    ) -> None:
        self._create_mapping_with_full_scopes()

        with self.assertRaisesRegex(ValueError, "Living artifacts are not enabled"):
            create_living_artifact(
                run=self.task_run,
                name="Summary",
                artifact_type=TaskArtifact.ArtifactType.SLACK_MESSAGE,
                content="Result",
            )

        mock_integration_for_mapping.assert_not_called()
        self.assertFalse(TaskArtifact.objects.for_team(self.team.id).exists())

    @parameterized.expand(
        [
            (
                "canvas",
                {"artifact_type": TaskArtifact.ArtifactType.SLACK_CANVAS, "content": "# Report"},
                "Slack canvas delivery is not enabled",
            ),
            (
                "file",
                {
                    "artifact_type": TaskArtifact.ArtifactType.SPREADSHEET,
                    "adapter": TaskArtifact.Adapter.SLACK_FILE,
                    "content_bytes": b"col_a,col_b",
                    "content_type": "text/csv",
                },
                "Slack file delivery is not enabled",
            ),
        ]
    )
    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=False)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_canvas_and_file_adapters_reject_when_flag_off(
        self, _name, create_kwargs, expected_error, mock_integration_for_mapping, _mock_flag
    ):
        self._create_mapping_with_full_scopes()

        with self.assertRaisesRegex(ValueError, expected_error):
            create_living_artifact(run=self.task_run, name="report", **create_kwargs)

        mock_integration_for_mapping.assert_not_called()
        self.assertFalse(TaskArtifact.objects.for_team(self.team.id).exists())

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=False)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_pending_file_delivery_skipped_when_flag_off(self, mock_integration_for_mapping, _mock_flag):
        self._create_mapping_with_full_scopes()
        storage_path = f"{self.task_run.get_artifact_s3_prefix()}/living/abc/report.v1.csv"
        artifact = TaskArtifact.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            task_run=self.task_run,
            name="report.csv",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            status=TaskArtifact.Status.ACTIVE,
            location={"kind": "slack_file", "storage_path": storage_path, "delivery_status": "pending"},
            versions=[
                {
                    "version": 1,
                    "delivery_status": "pending",
                    "location": {"storage_path": storage_path},
                }
            ],
            current_version=1,
        )

        delivered = deliver_pending_slack_file_artifacts(self.task_run, initial_comment="done")

        self.assertEqual(delivered, 0)
        mock_integration_for_mapping.assert_not_called()
        artifact.refresh_from_db()
        self.assertEqual(artifact.versions[0]["delivery_status"], "pending")


class TestRecordGithubPrArtifact(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    channel: ClassVar[Channel]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    PR_URL = "https://github.com/posthog/posthog/pull/1234"

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="pr-artifact@example.com", distinct_id="pr-artifact-user")
        # Direct instantiation sidesteps the fail-closed TeamScopedManager (see test_presence.py).
        cls.channel = Channel(team=cls.team, name="growth", created_by=cls.user)
        cls.channel.save()
        cls.task = Task.objects.create(
            team=cls.team,
            title="Fix the login redirect",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=cls.user,
            channel=cls.channel,
        )
        cls.task_run = TaskRun.objects.create(task=cls.task, team=cls.team, status=TaskRun.Status.IN_PROGRESS)

    def _rows(self):
        return TaskArtifact.objects.for_team(self.team.id).filter(artifact_type=TaskArtifact.ArtifactType.GITHUB_PR)

    def test_create_stamps_ownership_and_reference_fields(self):
        artifact = record_github_pr_artifact(
            self.task_run, self.PR_URL, state="open", title="Fix login redirect", repository="posthog/posthog"
        )
        assert artifact is not None
        self.assertEqual(artifact.task_id, self.task.id)
        self.assertEqual(artifact.task_run_id, self.task_run.id)
        self.assertEqual(artifact.channel_id, self.channel.id)
        self.assertEqual(artifact.created_by_id, self.user.id)
        self.assertEqual(artifact.name, "Fix login redirect")
        self.assertEqual(artifact.artifact_type, TaskArtifact.ArtifactType.GITHUB_PR)
        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.GITHUB_PR)
        self.assertEqual(artifact.location, {"url": self.PR_URL})
        self.assertEqual(
            artifact.metadata,
            {"title": "Fix login redirect", "repository": "posthog/posthog", "number": 1234, "state": "open"},
        )
        self.assertEqual(artifact.versions, [])

    def test_name_falls_back_to_repo_number_reference(self):
        artifact = record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        assert artifact is not None
        self.assertEqual(artifact.name, "posthog/posthog#1234")

    def test_upsert_updates_state_and_name_without_duplicating(self):
        record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        updated = record_github_pr_artifact(self.task_run, self.PR_URL, state="merged", title="Fix login redirect")
        assert updated is not None
        self.assertEqual(self._rows().count(), 1)
        self.assertEqual(updated.metadata["state"], "merged")
        self.assertEqual(updated.name, "Fix login redirect")

    def test_stale_open_event_does_not_reopen_finished_pr(self):
        record_github_pr_artifact(self.task_run, self.PR_URL, state="merged")
        artifact = record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        assert artifact is not None
        self.assertEqual(artifact.metadata["state"], "merged")

    def test_unique_index_rejects_duplicate_rows(self):
        record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskArtifact.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                task=self.task,
                name="duplicate",
                artifact_type=TaskArtifact.ArtifactType.GITHUB_PR,
                adapter=TaskArtifact.Adapter.GITHUB_PR,
                location={"url": self.PR_URL},
            )

    def test_losing_the_insert_race_falls_back_to_winners_row(self):
        winner = record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        assert winner is not None

        # Simulate the check-then-insert race: the existence check misses (as if the other
        # recorder's insert hadn't committed yet), the insert hits the unique index, and the
        # IntegrityError fallback must land on the winner's row instead of raising.
        real_first = QuerySet.first
        calls = {"n": 0}

        def miss_once(qs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return real_first(qs)

        with patch.object(QuerySet, "first", miss_once):
            artifact = record_github_pr_artifact(self.task_run, self.PR_URL, state="merged")

        assert artifact is not None
        self.assertEqual(artifact.id, winner.id)
        self.assertEqual(self._rows().count(), 1)
        self.assertEqual(artifact.metadata["state"], "merged")

    def test_failures_never_raise(self):
        self.assertIsNone(record_github_pr_artifact(self.task_run, None))  # type: ignore[arg-type]
        self.assertEqual(self._rows().count(), 0)

    @patch("products.tasks.backend.facade.api._record_github_pr_artifact_for_run")
    def test_set_task_run_output_records_only_on_pr_url_transition(self, mock_record):
        set_task_run_output(self.task_run.id, self.task.id, self.team.id, output={"pr_url": self.PR_URL})
        set_task_run_output(
            self.task_run.id, self.task.id, self.team.id, output={"pr_url": self.PR_URL, "summary": "done"}
        )
        self.assertEqual(mock_record.call_count, 1)
        self.assertEqual(mock_record.call_args[0][1], self.PR_URL)

    @patch("products.tasks.backend.facade.api._record_github_pr_artifact_for_run")
    def test_update_task_run_records_only_on_pr_url_transition(self, mock_record):
        update_task_run(
            self.task_run.id, self.task.id, self.team.id, validated_data={"output": {"pr_url": self.PR_URL}}
        )
        update_task_run(
            self.task_run.id,
            self.task.id,
            self.team.id,
            validated_data={"output": {"pr_url": self.PR_URL, "summary": "done"}},
        )
        self.assertEqual(mock_record.call_count, 1)

    def test_set_task_run_output_creates_the_artifact_row(self):
        set_task_run_output(self.task_run.id, self.task.id, self.team.id, output={"pr_url": self.PR_URL})
        artifact = self._rows().get()
        self.assertEqual(artifact.channel_id, self.channel.id)
        self.assertEqual(artifact.metadata["state"], "open")

    def test_same_pr_touched_by_another_task_gets_its_own_row(self):
        # The unique key is (task, url), not (team, url): a follow-up task in another
        # channel touching the same PR keeps its own provenance row, which is also what
        # surfaces the PR in that channel's artifact list.
        other_channel = Channel(team=self.team, name="mobile", created_by=self.user)
        other_channel.save()
        other_task = Task.objects.create(
            team=self.team,
            title="Follow up on the login redirect",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=other_channel,
        )
        other_run = TaskRun.objects.create(task=other_task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        second = record_github_pr_artifact(other_run, self.PR_URL, state="open")

        assert second is not None
        self.assertEqual(self._rows().count(), 2)
        self.assertEqual(second.task_id, other_task.id)
        self.assertEqual(second.channel_id, other_channel.id)

    def test_terminal_state_fans_out_to_sibling_rows(self):
        # The webhook resolves a merge to one run/task; the other tasks' rows for the
        # same PR must not claim an open PR forever.
        other_task = Task.objects.create(
            team=self.team,
            title="Follow up",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=self.channel,
        )
        other_run = TaskRun.objects.create(task=other_task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        unrelated_url = "https://github.com/posthog/posthog/pull/9999"

        mine = record_github_pr_artifact(self.task_run, self.PR_URL, state="open")
        sibling = record_github_pr_artifact(other_run, self.PR_URL, state="open")
        unrelated = record_github_pr_artifact(other_run, unrelated_url, state="open")
        assert mine is not None and sibling is not None and unrelated is not None

        record_github_pr_artifact(self.task_run, self.PR_URL, state="merged")

        sibling.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertEqual(sibling.metadata["state"], "merged")
        self.assertEqual(unrelated.metadata["state"], "open")
