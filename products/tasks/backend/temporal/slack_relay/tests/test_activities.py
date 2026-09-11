from datetime import timedelta
from typing import ClassVar

import unittest
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase, override_settings

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.helpers.slack_markdown import SLACK_MARKDOWN_TEXT_MAX_LEN
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.logic.services.living_artifacts import SlackFileDeliveryResult
from products.tasks.backend.models import Task, TaskArtifact, TaskRun
from products.tasks.backend.temporal.slack_relay.activities import (
    RelaySlackMessageInput,
    _append_unconfirmed_attachment_notice,
    _split_markdown_for_slack,
    relay_slack_message,
)


class TestRelaySlackMessage(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.user = User.objects.create(email="alice@test.com")

        cls.task = Task.objects.create(
            team=cls.team,
            title="Test task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=cls.user,
            repository="org/repo",
        )
        cls.task_run = TaskRun.objects.create(
            task=cls.task,
            team=cls.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="slack",
            integration_id="T123",
            config={},
        )
        SlackThreadTaskMapping.objects.create(
            team=cls.team,
            integration=cls.integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=cls.task,
            task_run=cls.task_run,
            mentioning_slack_user_id="U123",
        )

    def setUp(self):
        self.task_run.artifacts = []
        self.task_run.state = {}
        self.task_run.save(update_fields=["artifacts", "state", "updated_at"])
        SlackThreadTaskMapping.objects.filter(task_run=self.task_run).update(latest_actor_slack_user_id=None)

    @parameterized.expand(
        [
            ("no_reaction_emoji", "relay-1", "Which license should I use?", None),
            ("explicit_reaction_emoji", "relay-2", "Could not deliver follow-up", "x"),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_relay_posts_message_and_marks_sent(
        self,
        _name,
        relay_id,
        text,
        reaction_emoji,
        mock_delete_progress,
        mock_post,
        mock_update,
    ):
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id=relay_id,
                text=text,
                user_message_ts="1234.5",
                reaction_emoji=reaction_emoji,
            )
        )

        mock_delete_progress.assert_called_once()
        mock_post.assert_called_once()
        assert text in mock_post.call_args.args[0]
        if reaction_emoji is None:
            mock_update.assert_not_called()
        else:
            mock_update.assert_called_once_with(reaction_emoji)
        self.task_run.refresh_from_db()
        assert relay_id in self.task_run.state.get("slack_sent_relay_ids", [])

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message", autospec=True)
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_relay_hands_the_reply_the_turns_trace_id(self, _mock_delete_progress, mock_post):
        # The posted reply is the only place the turn's trace id survives.
        trace_id = "f960aead-b2af-4ee0-b0eb-630109a1b2a0"

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id), relay_id="relay-trace", text="Done.", trace_id=trace_id
            )
        )

        assert mock_post.call_args.args[0].turn_trace_id == trace_id

    _RICH_ANSWER = "## Heading\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n- [ ] todo"

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_the_answer_reaches_slack_as_the_agent_wrote_it(self, mock_delete_progress, mock_post):
        # A markdown block renders headings, tables, and task lists on its own, so the answer
        # goes out untouched. Rewriting any of it here would flatten what the block renders.
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-conversion",
                text=self._RICH_ANSWER,
            )
        )

        assert mock_post.call_args.args[0].endswith(self._RICH_ANSWER)

    @parameterized.expand(
        [
            ("heading", "## Heading\n\nBody text.", "<@U123>\n\n## Heading"),
            ("prose", "Done. Your model is set.", "<@U123> Done."),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_the_mention_leaves_the_answers_opening_line_only_where_markdown_needs_it(
        self, _name, text, expected_opening, mock_delete_progress, mock_post
    ):
        # Markdown reads a heading only at the start of a line, so a mention glued to the front of
        # that answer renders the `##` as literal text. An answer that opens with prose has no such
        # constraint, and reads as one message with the mention in its first line.
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id=f"relay-mention-{_name}",
                text=text,
            )
        )

        assert mock_post.call_args.args[0].startswith(expected_opening)

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_the_mention_comes_out_of_the_chunk_budget(self, mock_delete_progress, mock_post):
        # The mention is added after splitting, so without a reserved allowance the chunk it
        # lands on exceeds the block cap and posts as plain text, showing the Markdown source.
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-mention-budget",
                text="word " * 4000,  # 20,000 chars, so the first chunk fills the block
            )
        )

        assert all(len(call.args[0]) <= SLACK_MARKDOWN_TEXT_MAX_LEN for call in mock_post.call_args_list)

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_relay_does_not_post_when_claim_write_fails(self, mock_delete_progress, mock_post):
        with (
            patch.object(TaskRun, "mutate_state_atomic", side_effect=DatabaseError("read-only")),
            self.assertRaises(DatabaseError),
        ):
            relay_slack_message(
                RelaySlackMessageInput(run_id=str(self.task_run.id), relay_id="relay-claim-fails", text="Done.")
            )

        mock_delete_progress.assert_not_called()
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            # ``mentioning_slack_user_id`` is the immutable thread creator;
            # ``latest_actor_slack_user_id`` is set by the follow-up handler
            # when someone else (or the creator themselves) replies. The bot
            # tags the latest actor when present, otherwise the creator.
            ("no_actor_falls_back_to_mentioner", None, "<@U123> "),
            ("actor_overrides_mentioner", "UBOB", "<@UBOB> "),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_mention_prefix_uses_latest_actor_then_mentioner(
        self,
        _name,
        latest_actor,
        expected_prefix,
        _mock_delete_progress,
        mock_post,
        _mock_update,
    ):
        SlackThreadTaskMapping.objects.filter(task_run=self.task_run).update(latest_actor_slack_user_id=latest_actor)

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id=f"relay-mention-{_name}",
                text="agent reply",
            )
        )

        mock_post.assert_called_once()
        assert mock_post.call_args.args[0].startswith(expected_prefix)

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_labeled_mention_echoed_in_body_is_posted_as_bare(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
    ):
        # The agent echoes participants in the labeled ``<@U…|display name>`` form fed to it.
        # That form does not reliably notify when the bot posts it, so the relay must rewrite
        # it to the bare ``<@U…>`` — otherwise a display name with a space (here "Radu Raicea")
        # renders as inert text and the mentioned user is never pinged.
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-labeled-mention",
                text="Answering <@U094TR1E59V|Radu Raicea> now.",
            )
        )

        mock_post.assert_called_once()
        posted = mock_post.call_args.args[0]
        assert "<@U094TR1E59V>" in posted
        assert "Radu Raicea" not in posted

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_unconfirmed_attachment_claim_gets_notice(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
    ):
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-unconfirmed-attachment",
                text=(
                    "Done. I generated **user_activity_report.pdf** "
                    "at /tmp/workspace/user_activity_report.pdf and it's attached for you."
                ),
            )
        )

        mock_post.assert_called_once()
        posted = mock_post.call_args.args[0]
        assert "user_activity_report.pdf" in posted
        assert "no file was attached to Slack for this run" in posted

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_run_manifest_artifacts_never_surface_in_slack(self, _mock_delete_progress, mock_post, _mock_update):
        # Run-manifest artifacts are internal (inputs, context, raw agent outputs).
        # Even with living artifacts enabled they must not leak into the posted text,
        # and their presence must not suppress the unconfirmed-attachment notice.
        self.task_run.artifacts = [
            {
                "id": "artifact-1",
                "name": "report.pdf",
                "type": "output",
                "source": "agent_output",
                "content_type": "application/pdf",
                "storage_path": "tasks/artifacts/report.pdf",
            }
        ]
        self.task_run.save(update_fields=["artifacts", "updated_at"])

        text = "Done. report.pdf is attached."
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-manifest-artifacts",
                text=text,
            )
        )

        mock_post.assert_called_once()
        posted = mock_post.call_args.args[0]
        assert "Artifacts available in Slack" not in posted
        assert "tasks/artifacts/report.pdf" not in posted
        assert "no file was attached to Slack for this run" in posted

    def _create_pending_slack_file_artifact(
        self, *, name: str, filename: str, content_type: str, metadata: dict, export_asset_id: int | None = None
    ) -> tuple[TaskArtifact, str]:
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{self.task_run.id}/{filename}"
        location = {
            "kind": "slack_file",
            "integration_id": self.integration.id,
            "channel": "C123",
            "thread_ts": "1111.1",
            "content_type": content_type,
            "storage_path": storage_path,
            "delivery_status": "pending",
        }
        artifact = TaskArtifact.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            task_run=self.task_run,
            created_by=self.user,
            name=name,
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            status=TaskArtifact.Status.ACTIVE,
            location=location,
            metadata={"delivery_status": "pending", **metadata},
            export_asset_id=export_asset_id,
            versions=[
                {
                    "version": 1,
                    "run_id": str(self.task_run.id),
                    "adapter": TaskArtifact.Adapter.SLACK_FILE,
                    "location": location,
                    "content_type": content_type,
                    "size": 14,
                    "delivery_status": "pending",
                }
            ],
            current_version=1,
        )
        return artifact, storage_path

    @staticmethod
    def _mock_slack_upload(mock_integration_for_mapping, *, file_id: str = "F123", title: str = "report.xlsx"):
        slack = unittest.mock.MagicMock()
        slack.api_call.side_effect = [
            {"upload_url": "https://files.slack.test/upload", "file_id": file_id},
            {"files": [{"id": file_id, "title": title, "permalink": f"https://slack.test/files/{file_id}"}]},
        ]
        slack_integration = unittest.mock.MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration
        return slack

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_pending_slack_file_upload_posts_text_then_file(
        self,
        mock_delete_progress,
        mock_post,
        _mock_update,
        mock_integration_for_mapping,
        mock_read_bytes,
        mock_requests_post,
    ):
        artifact, storage_path = self._create_pending_slack_file_artifact(
            name="report.xlsx",
            filename="report.v1.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={},
        )
        slack = self._mock_slack_upload(mock_integration_for_mapping)
        mock_read_bytes.return_value = b"workbook bytes"

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-with-file",
                text="Done. report.xlsx is attached.",
            )
        )

        mock_delete_progress.assert_called_once()
        mock_post.assert_called_once()
        self.assertIn("<@U123> Done. report.xlsx is attached.", mock_post.call_args.args[0])
        mock_read_bytes.assert_called_once_with(storage_path, missing_ok=True)
        self.assertEqual(mock_requests_post.call_args.kwargs["data"], b"workbook bytes")
        complete_payload = slack.api_call.call_args_list[1].kwargs["data"]
        self.assertEqual(complete_payload["channel_id"], "C123")
        self.assertEqual(complete_payload["thread_ts"], "1111.1")
        self.assertNotIn("initial_comment", complete_payload)

        artifact.refresh_from_db()
        self.assertEqual(artifact.location["delivery_status"], "delivered")
        self.assertEqual(artifact.location["file_id"], "F123")
        self.assertEqual(artifact.metadata["slack_file_permalink"], "https://slack.test/files/F123")
        self.assertEqual(artifact.versions[0]["delivery_status"], "delivered")
        self.assertEqual(artifact.versions[0]["slack_file_id"], "F123")

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    @patch(
        "products.tasks.backend.logic.services.living_artifacts.get_delivery_image_url",
        return_value="http://localhost:8010/exporter/export-chart.png?token=abc",
    )
    @override_settings(SITE_URL="http://localhost:8010")
    def test_chart_composes_single_message_with_answer_image_and_button(
        self,
        mock_delivery_url,
        _mock_delete_progress,
        mock_post,
        _mock_update,
        mock_integration_for_mapping,
        mock_read_bytes,
        _mock_requests_post,
    ):
        # posthog_url must be SITE_URL-origin, or it is treated as untrusted caller metadata
        # and no button is added.
        chart_url = "http://localhost:8010/project/1/insights/abc123"
        artifact, _storage_path = self._create_pending_slack_file_artifact(
            name="Signups by week",
            filename="signups.v1.png",
            content_type="image/png",
            metadata={"posthog_url": chart_url},
            export_asset_id=321,
        )
        slack = unittest.mock.MagicMock()
        slack_integration = unittest.mock.MagicMock()
        slack_integration.client = slack
        # No files:write — url-referenced charts must deliver without any file scope.
        slack_integration.missing_scopes.return_value = {"files:write"}
        mock_integration_for_mapping.return_value = slack_integration
        # First post rejected transiently to exercise the retry.
        slack.chat_postMessage.side_effect = [
            SlackApiError("invalid_blocks", {"ok": False, "error": "invalid_blocks"}),
            {"ok": True, "ts": "1111.2"},
        ]

        with patch("products.tasks.backend.logic.services.living_artifacts.time.sleep") as mock_sleep:
            relay_slack_message(
                RelaySlackMessageInput(
                    run_id=str(self.task_run.id),
                    relay_id="relay-with-chart",
                    text="Here's the trend.",
                )
            )
        mock_sleep.assert_called_once()

        # url-referenced images involve no upload at all: no files.* API calls, no
        # object storage read — Slack fetches the PNG from the url in the block.
        slack.api_call.assert_not_called()
        mock_read_bytes.assert_not_called()
        self.assertEqual(slack.chat_postMessage.call_count, 2)
        composed_call = slack.chat_postMessage.call_args
        self.assertEqual(composed_call.kwargs["channel"], "C123")
        self.assertEqual(composed_call.kwargs["thread_ts"], "1111.1")
        answer_block, header_block, image_block, actions_block = composed_call.kwargs["blocks"]
        self.assertEqual(answer_block["text"]["text"], "<@U123> Here's the trend.")
        self.assertEqual(header_block["text"]["text"], "*Signups by week*")
        self.assertEqual(
            image_block,
            {
                "type": "image",
                "image_url": "http://localhost:8010/exporter/export-chart.png?token=abc",
                "alt_text": "Signups by week",
            },
        )
        # Minted from the stored reference at post time, scoped to this run's team.
        self.assertEqual(
            mock_delivery_url.call_args.kwargs,
            {"team_id": self.team.id, "asset_id": 321, "expiry_delta": timedelta(days=30)},
        )
        button = actions_block["elements"][0]
        self.assertEqual(button["url"], chart_url)
        self.assertEqual(button["text"]["text"], "Open in PostHog")

        # The composed message carries the answer text — nothing posted via the handler.
        mock_post.assert_not_called()

        artifact.refresh_from_db()
        self.assertEqual(artifact.location["delivery_status"], "delivered")
        self.assertNotIn("slack_file_id", artifact.versions[0])
        self.assertEqual(artifact.versions[0]["delivery_status"], "delivered")

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    @override_settings(SITE_URL="http://localhost:8010")
    def test_chart_without_image_url_uploads_privately_then_references_the_file(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
        mock_integration_for_mapping,
        mock_read_bytes,
        _mock_requests_post,
    ):
        artifact, _storage_path = self._create_pending_slack_file_artifact(
            name="Signups by week",
            filename="signups.v1.png",
            content_type="image/png",
            metadata={"posthog_url": "http://localhost:8010/project/1/insights/abc123"},
        )
        slack = self._mock_slack_upload(mock_integration_for_mapping, title="Signups by week")
        slack.chat_postMessage.return_value = {"ok": True, "ts": "1111.2"}
        mock_read_bytes.return_value = b"png bytes"

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-chart-upload",
                text="Here's the trend.",
            )
        )

        # Sharing the upload to the channel would make Slack materialize a second copy
        # alongside the image block in the composed message.
        complete_payload = slack.api_call.call_args_list[1].kwargs["data"]
        self.assertNotIn("channel_id", complete_payload)
        self.assertNotIn("thread_ts", complete_payload)

        slack.chat_postMessage.assert_called_once()
        _answer_block, _header_block, image_block, _actions_block = slack.chat_postMessage.call_args.kwargs["blocks"]
        self.assertEqual(image_block, {"type": "image", "slack_file": {"id": "F123"}, "alt_text": "Signups by week"})
        mock_post.assert_not_called()

        artifact.refresh_from_db()
        self.assertEqual(artifact.location["delivery_status"], "delivered")
        self.assertEqual(artifact.versions[0]["delivery_status"], "delivered")
        self.assertEqual(artifact.versions[0]["slack_file_id"], "F123")

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_failed_chart_post_leaves_artifact_pending(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
        mock_integration_for_mapping,
        mock_read_bytes,
        _mock_requests_post,
    ):
        artifact, _storage_path = self._create_pending_slack_file_artifact(
            name="Signups by week",
            filename="signups.v1.png",
            content_type="image/png",
            metadata={"posthog_url": "https://us.posthog.com/project/1/insights/abc123"},
        )
        slack = self._mock_slack_upload(mock_integration_for_mapping, title="Signups by week")
        # A non-retryable post failure must leave the artifact pending for the next
        # relay — marking it delivered would lose the chart (it was never shared).
        slack.chat_postMessage.side_effect = SlackApiError(
            "channel_not_found", {"ok": False, "error": "channel_not_found"}
        )
        mock_read_bytes.return_value = b"png bytes"

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-chart-post-fails",
                text="Here's the trend.",
            )
        )

        artifact.refresh_from_db()
        self.assertEqual(artifact.versions[0]["delivery_status"], "pending")
        self.assertEqual(artifact.location["delivery_status"], "pending")
        mock_post.assert_called_once_with("<@U123> Here's the trend.", with_footer=True, markdown=True)


class TestAppendUnconfirmedAttachmentNotice(unittest.TestCase):
    def test_appends_notice_for_local_file_delivery_claim_without_artifacts(self):
        text = "Generated /tmp/workspace/report.pdf and it is attached."
        result = _append_unconfirmed_attachment_notice(text, origin_product="slack")

        assert result.endswith("no file was attached to Slack for this run._")

    def test_skips_notice_for_negated_claim(self):
        text = "Generated /tmp/workspace/report.pdf, but it is not attached yet."
        result = _append_unconfirmed_attachment_notice(text, origin_product="slack")

        assert result == text

    def test_skips_notice_for_non_slack_run(self):
        text = "Generated /tmp/workspace/report.pdf and it is attached."
        result = _append_unconfirmed_attachment_notice(text, origin_product="user_created")

        assert result == text


class TestSplitTextForSlack(TestCase):
    _LIMIT = 3500

    def test_short_text_returns_single_chunk(self):
        assert _split_markdown_for_slack("hello world", self._LIMIT) == ["hello world"]

    def test_each_chunk_under_limit(self):
        paragraph = ("word " * 200).strip()
        text = "\n\n".join([paragraph] * 10)
        chunks = _split_markdown_for_slack(text, self._LIMIT)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= self._LIMIT

    def test_split_prefers_paragraph_boundary(self):
        paragraph = ("alpha " * 400).strip()  # ~2400 chars per paragraph
        text = f"{paragraph}\n\n{paragraph}"
        chunks = _split_markdown_for_slack(text, self._LIMIT)
        assert len(chunks) == 2
        assert chunks[0] == paragraph
        assert chunks[1] == paragraph

    def test_split_falls_back_to_line_within_paragraph(self):
        line = ("alpha " * 100).strip()  # ~600 chars
        text = "\n".join([line] * 10)  # single paragraph, ~6000 chars
        chunks = _split_markdown_for_slack(text, self._LIMIT)
        assert len(chunks) >= 2
        for chunk in chunks:
            for chunk_line in chunk.split("\n"):
                assert chunk_line == line

    def test_hard_breaks_single_long_line(self):
        line = "x" * (self._LIMIT + 500)
        chunks = _split_markdown_for_slack(line, self._LIMIT)
        assert len(chunks) == 2
        assert all(len(chunk) <= self._LIMIT for chunk in chunks)
        assert "".join(chunks) == line

    def test_oversized_code_block_keeps_fences_balanced(self):
        body_lines = [f"line {i:04d}" for i in range(800)]
        body = "\n".join(body_lines)
        text = f"```python\n{body}\n```"
        chunks = _split_markdown_for_slack(text, self._LIMIT)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.startswith("```python\n")
            assert chunk.endswith("\n```")
            assert chunk.count("```") == 2
            assert len(chunk) <= self._LIMIT

    def test_mixed_text_and_code_block_preserves_block(self):
        prefix = "intro paragraph\n\n"
        suffix = "\n\ntrailing paragraph"
        code = "```js\n" + "console.log('hi');\n" * 10 + "```"
        text = prefix + code + suffix
        chunks = _split_markdown_for_slack(text, self._LIMIT)
        joined = "\n\n".join(chunks)
        assert "```js\n" in joined
        assert joined.count("```") % 2 == 0


class TestRelaySlackMessageChunking(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="ChunkOrg")
        cls.team = Team.objects.create(organization=cls.org, name="ChunkTeam")
        cls.user = User.objects.create(email="bob@test.com")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Chunk task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=cls.user,
            repository="org/repo",
        )
        cls.task_run = TaskRun.objects.create(
            task=cls.task,
            team=cls.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="slack",
            integration_id="T456",
            config={},
        )
        SlackThreadTaskMapping.objects.create(
            team=cls.team,
            integration=cls.integration,
            slack_workspace_id="T456",
            channel="C456",
            thread_ts="2222.2",
            task=cls.task,
            task_run=cls.task_run,
            mentioning_slack_user_id="U456",
        )

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_long_text_posts_multiple_chunks_with_prefix_only_on_first(
        self,
        mock_delete_progress,
        mock_post,
        mock_update,
    ):
        paragraph = ("alpha " * 1000).strip()  # ~6000 chars
        text = "\n\n".join([paragraph] * 3)
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-chunked",
                text=text,
                user_message_ts="1234.5",
                reaction_emoji="hedgehog",
            )
        )

        mock_delete_progress.assert_called_once()
        assert mock_post.call_count >= 2
        first_posted = mock_post.call_args_list[0].args[0]
        assert first_posted.startswith("<@U456> ")
        for call in mock_post.call_args_list[1:]:
            assert not call.args[0].startswith("<@U456>")
        mock_update.assert_called_once_with("hedgehog")

        self.task_run.refresh_from_db()
        assert "relay-chunked" in self.task_run.state.get("slack_sent_relay_ids", [])

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_footer")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    @patch("products.tasks.backend.temporal.slack_relay.activities.has_pending_slack_image_artifacts")
    @patch("products.tasks.backend.temporal.slack_relay.activities.deliver_pending_slack_file_artifacts")
    @patch("products.tasks.backend.temporal.slack_relay.activities.has_pending_slack_file_artifacts")
    def test_answer_composed_with_charts_still_gets_its_footer(
        self,
        mock_has_files,
        mock_deliver,
        mock_has_images,
        mock_delete_progress,
        mock_post,
        mock_post_footer,
    ):
        # The answer rides out inside the composed chart message, leaving no message of its
        # own to close — without this the reply would carry no provenance at all.
        mock_has_files.return_value = True
        mock_has_images.return_value = True
        mock_deliver.return_value = SlackFileDeliveryResult(answer_posted=True, delivered_count=1)

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-composed-charts",
                text="Here you go.",
                user_message_ts="1234.5",
            )
        )

        mock_post.assert_not_called()
        mock_post_footer.assert_called_once()

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_footer")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    @patch("products.tasks.backend.temporal.slack_relay.activities.has_pending_slack_image_artifacts")
    @patch("products.tasks.backend.temporal.slack_relay.activities.deliver_pending_slack_file_artifacts")
    @patch("products.tasks.backend.temporal.slack_relay.activities.has_pending_slack_file_artifacts")
    def test_answer_falls_back_to_plain_messages_when_compose_does_not_post(
        self,
        mock_has_files,
        mock_deliver,
        mock_has_images,
        mock_delete_progress,
        mock_post,
        mock_post_footer,
    ):
        # Compose was attempted but the message never landed, so the answer is posted the
        # ordinary way and closes itself — a second standalone footer would duplicate it.
        mock_has_files.return_value = True
        mock_has_images.return_value = True
        mock_deliver.return_value = SlackFileDeliveryResult(answer_posted=False)

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-compose-failed",
                text="Here you go.",
                user_message_ts="1234.5",
            )
        )

        mock_post.assert_called_once_with("<@U456> Here you go.", with_footer=True, markdown=True)
        mock_post_footer.assert_not_called()
