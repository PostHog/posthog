import io
import time
import zipfile
from typing import Any, ClassVar

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.exports.backend.models.exported_asset import ExportedAsset
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.logic.services.living_artifacts import (
    _SLACK_CODE_FENCE,
    _SLACK_MESSAGE_BLOCK_LIMIT,
    DEFAULT_DOCUMENT_CONTENT_TYPE,
    ArtifactCommit,
    DocumentConnectorUnavailable,
    _chart_card_blocks,
    _post_composed_answer_message,
    _section_blocks,
    _SlackImageCard,
    create_living_artifact,
    deliver_pending_slack_file_artifacts,
    edit_living_artifact,
    get_task_artifact_for_run,
    get_task_artifacts_for_run,
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
        export_asset_id: int | None = None,
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

    def _create_scopeless_mapping(self, mock_integration_for_mapping) -> None:
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

    @override_settings(SITE_URL="http://localhost:8010")
    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_allows_chart_images_with_own_export_without_file_scope(
        self, mock_integration_for_mapping, _mock_flag
    ):
        # Chart images deliver as image blocks pointing at a PostHog-hosted url — no upload,
        # no files:write.
        self._create_scopeless_mapping(mock_integration_for_mapping)
        asset = ExportedAsset.objects.create(team=self.team, export_format=ExportedAsset.ExportFormat.PNG)

        artifact = create_living_artifact(
            run=self.task_run,
            name="Signups by week.png",
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=b"png-bytes",
            content_type="image/png",
            export_asset_id=asset.id,
        )

        self.assertEqual(artifact.adapter, TaskArtifact.Adapter.SLACK_FILE)
        self.assertEqual(artifact.location["delivery_status"], "pending")
        self.assertEqual(artifact.export_asset_id, asset.id)
        # The delivery token bypasses the org's publicly-shared-resources setting and metadata
        # is readable with only task:read, so it must never be stored — delivery mints it.
        self.assertNotIn("image_url", artifact.metadata)

    def _foreign_team_asset_id(self) -> int:
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        return ExportedAsset.objects.create(team=other_team, export_format=ExportedAsset.ExportFormat.PNG).id

    def _non_image_asset_id(self) -> int:
        return ExportedAsset.objects.create(team=self.team, export_format=ExportedAsset.ExportFormat.CSV).id

    @parameterized.expand(
        [
            ("no_export_asset", lambda _self: None),
            ("unknown_export_asset", lambda _self: 987654),
            ("export_asset_from_another_team", lambda self: self._foreign_team_asset_id()),
            # An image block is the only thing delivery posts, so a non-image asset must not
            # mint either — otherwise a leaked reference could pull down a CSV.
            ("export_asset_that_is_not_an_image", lambda self: self._non_image_asset_id()),
        ]
    )
    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_slack_file_adapter_rejects_images_without_a_resolvable_export(
        self, _name, asset_id_factory, mock_integration_for_mapping, _mock_flag
    ):
        self._create_scopeless_mapping(mock_integration_for_mapping)

        with self.assertRaisesRegex(ValueError, "files:write"):
            create_living_artifact(
                run=self.task_run,
                name="screenshot.png",
                artifact_type=TaskArtifact.ArtifactType.FILE,
                adapter=TaskArtifact.Adapter.SLACK_FILE,
                content_bytes=b"png-bytes",
                content_type="image/png",
                export_asset_id=asset_id_factory(self),
            )

        self.assertFalse(TaskArtifact.objects.for_team(self.team.id).exists())

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

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_caller_metadata_cannot_link_an_export_asset(self, mock_integration_for_mapping, _mock_flag):
        # Anyone with task:write can pass metadata here, and the export link is what lets
        # delivery mint an anonymous url for someone else's export. It lives in its own
        # column, which caller metadata must never populate.
        self._create_mapping_with_full_scopes()
        mock_integration_for_mapping.return_value.missing_scopes.return_value = set()

        artifact = create_living_artifact(
            run=self.task_run,
            name="chart.png",
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=b"png-bytes",
            content_type="image/png",
            metadata={"export_asset_id": 4321, "posthog_url": "http://localhost:8010/project/1/insights/abc"},
        )

        self.assertIsNone(artifact.export_asset_id)
        self.assertEqual(artifact.metadata["posthog_url"], "http://localhost:8010/project/1/insights/abc")

        # Nor by retrofitting one onto an artifact that already exists.
        updated = edit_living_artifact(
            artifact=artifact,
            content_bytes=b"png-bytes-v2",
            content_type="image/png",
            metadata={"export_asset_id": 4321},
        )
        self.assertIsNone(updated.export_asset_id)

    @patch("products.tasks.backend.logic.services.living_artifacts._canvas_file_artifacts_enabled", return_value=True)
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    def test_editing_a_chart_drops_its_export_link(self, mock_integration_for_mapping, _mock_flag):
        # The export depicts the version it was rendered from, so a new version must not
        # deliver the old picture.
        self._create_mapping_with_full_scopes()
        mock_integration_for_mapping.return_value.missing_scopes.return_value = set()
        artifact = create_living_artifact(
            run=self.task_run,
            name="chart.png",
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=b"png-bytes",
            content_type="image/png",
            export_asset_id=321,
        )
        self.assertEqual(artifact.export_asset_id, 321)
        self.assertNotIn("export_asset_id", artifact.metadata)

        updated = edit_living_artifact(artifact=artifact, content_bytes=b"png-bytes-v2", content_type="image/png")

        self.assertIsNone(updated.export_asset_id)

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

        delivery = deliver_pending_slack_file_artifacts(self.task_run)

        self.assertFalse(delivery.answer_posted)
        self.assertEqual(delivery.delivered_count, 0)
        mock_integration_for_mapping.assert_not_called()
        artifact.refresh_from_db()
        self.assertEqual(artifact.versions[0]["delivery_status"], "pending")


@override_settings(SITE_URL="http://localhost:8010")
class TestChartCardBlockBuilders(SimpleTestCase):
    @parameterized.expand(
        [
            ("url_within_limit", "http://localhost:8010/project/1/insights/abc", ["section", "image", "actions"]),
            (
                "url_over_slack_button_cap",
                "http://localhost:8010/project/1/insights/new#q=" + "x" * 3000,
                ["section", "image"],
            ),
            # Artifact metadata is caller-writable, so an off-origin url must not become a button
            # the PostHog bot appears to vouch for.
            ("url_off_posthog_origin", "https://phishing.example/project/1/insights/abc", ["section", "image"]),
        ]
    )
    def test_button_only_added_for_trusted_url_within_slack_cap(self, _name, url, expected_block_types):
        artifact = TaskArtifact(name="Chart", metadata={"posthog_url": url})
        blocks = _chart_card_blocks(_SlackImageCard(artifact, {}, file_id="F123"))
        self.assertEqual([b["type"] for b in blocks], expected_block_types)

    def test_oversized_sections_split_below_block_char_cap(self):
        blocks = _section_blocks(["a" * 6500, "short"])
        self.assertEqual([len(b["text"]["text"]) for b in blocks], [3000, 3000, 500, 5])
        self.assertEqual(blocks[-1]["text"]["text"], "short")

    def test_oversized_sections_split_at_whitespace_so_mrkdwn_entities_survive(self):
        # A hard character slice can cut a converted entity like `<url|text>` in half;
        # the split must land on whitespace when any is available in the window.
        words = "word " * 1300  # 6500 chars of 5-char words
        blocks = _section_blocks([words.strip()])
        self.assertGreater(len(blocks), 1)
        for block in blocks:
            text = block["text"]["text"]
            self.assertLessEqual(len(text), 3000)
            self.assertEqual(set(text.split(" ")), {"word"})

    def test_oversized_fenced_section_is_closed_and_reopened_around_the_split(self):
        # Tables convert to fenced blocks before this re-split, so a cut inside one would
        # leave an unclosed fence in one block and a stray closer in the next.
        table = "| cell | cell |\n" * 250
        blocks = _section_blocks([f"{_SLACK_CODE_FENCE}\n{table}{_SLACK_CODE_FENCE}"])
        self.assertGreater(len(blocks), 1)
        for block in blocks:
            text = block["text"]["text"]
            self.assertLessEqual(len(text), 3000)
            self.assertEqual(text.count(_SLACK_CODE_FENCE) % 2, 0)
            self.assertTrue(text.startswith(_SLACK_CODE_FENCE))
            self.assertTrue(text.endswith(_SLACK_CODE_FENCE))

    def test_fenced_whitespace_free_content_terminates_and_stays_balanced(self):
        # After a fence is closed and reopened, the only whitespace in the window can be
        # the reopen prefix's own newline — cutting there consumes nothing of the content.
        section = f"{_SLACK_CODE_FENCE}\n{'x' * 8000}\n{_SLACK_CODE_FENCE}"
        blocks = _section_blocks([section])
        self.assertGreater(len(blocks), 1)
        for block in blocks:
            text = block["text"]["text"]
            self.assertLessEqual(len(text), 3000)
            self.assertEqual(text.count(_SLACK_CODE_FENCE) % 2, 0)
        self.assertIn(
            "x" * 8000,
            "".join(b["text"]["text"] for b in blocks)
            .replace(f"\n{_SLACK_CODE_FENCE}", "")
            .replace(f"{_SLACK_CODE_FENCE}\n", ""),
        )

    def test_card_without_a_minted_url_references_the_uploaded_file(self):
        card = _SlackImageCard(TaskArtifact(name="Chart"), {}, file_id="F123")
        blocks = _chart_card_blocks(card)
        self.assertEqual(blocks[1], {"type": "image", "slack_file": {"id": "F123"}, "alt_text": "Chart"})

    def test_card_with_a_minted_url_references_it_directly(self):
        image_url = "http://localhost:8010/exporter/export-1.png?token=abc"
        card = _SlackImageCard(TaskArtifact(name="Chart"), {}, image_url=image_url)
        blocks = _chart_card_blocks(card)
        self.assertEqual(blocks[1], {"type": "image", "image_url": image_url, "alt_text": "Chart"})

    @parameterized.expand(
        [
            ("composed", 1),
            # Two blocks per card, so this many cards overflows the cap and takes the per-card path.
            ("per_card", _SLACK_MESSAGE_BLOCK_LIMIT // 2 + 1),
        ]
    )
    def test_mention_shaped_artifact_name_is_escaped_in_message_text(self, _name, card_count):
        # Artifact names are task-controlled and Slack parses a message's top-level text as
        # mrkdwn, so an unescaped name could notify a channel as the PostHog bot.
        slack = MagicMock()
        slack.chat_postMessage.return_value = {"ok": True, "ts": "1111.2"}
        cards = [
            _SlackImageCard(TaskArtifact(name="<!channel> spike.png"), {}, file_id=f"F{index}")
            for index in range(card_count)
        ]

        _post_composed_answer_message(
            slack,
            mapping=MagicMock(channel="C123", thread_ts="1111.1"),
            image_cards=cards,
            answer_sections=[],
            mark_delivered=lambda card: None,
            deadline=time.monotonic() + 30,
        )

        self.assertEqual(slack.chat_postMessage.call_count, 1 if card_count == 1 else card_count)
        for call in slack.chat_postMessage.call_args_list:
            self.assertEqual(call.kwargs["text"], "&lt;!channel&gt; spike")

    @parameterized.expand(
        [
            ("composed", 1),
            ("per_card", _SLACK_MESSAGE_BLOCK_LIMIT // 2 + 1),
        ]
    )
    def test_deleted_prompt_skips_delivery_without_marking_cards_delivered(self, _name, card_count):
        # A prompt deleted mid-delivery makes the reply funnel skip the post and return None.
        # A skipped post must not read as delivered: the chart never reached the thread, and
        # marking it delivered would drop it from every later relay pass.
        slack = MagicMock()
        slack.conversations_history.return_value = {"messages": []}  # the message is gone
        delivered: list[_SlackImageCard] = []
        cards = [_SlackImageCard(TaskArtifact(name="Chart"), {}, file_id=f"F{index}") for index in range(card_count)]

        answer_posted = _post_composed_answer_message(
            slack,
            mapping=MagicMock(channel="C_DELETED", thread_ts="8888.1"),
            image_cards=cards,
            answer_sections=[],
            mark_delivered=delivered.append,
            deadline=time.monotonic() + 30,
        )

        self.assertEqual(delivered, [])
        slack.chat_postMessage.assert_not_called()
        self.assertFalse(answer_posted)
