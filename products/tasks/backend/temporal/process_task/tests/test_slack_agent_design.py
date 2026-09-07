from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.exports.backend.models.exported_asset import ExportedAsset
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.logic.services.living_artifacts import create_living_artifact
from products.tasks.backend.models import Task, TaskArtifact, TaskRun
from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    StopSlackAgentDesignStreamInput,
    stop_slack_agent_design_stream,
)


@override_settings(SITE_URL="https://us.posthog.com")
class TestSlackAgentDesignStream(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.integration = Integration.objects.create(team=cls.team, kind="slack", integration_id="T123", config={})

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream")
    def test_streamed_final_answer_has_object_tags_rewritten(self, mock_stop) -> None:
        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                ts="2.0",
                final_markdown='The <insight id="9pQx3">checkout funnel</insight> dropped.',
            )
        )

        mock_stop.assert_called_once()
        final_markdown = mock_stop.call_args.kwargs["final_markdown"]
        assert final_markdown == (
            f"The [checkout funnel](https://us.posthog.com/project/{self.team.id}/insights/9pQx3?unfurl=false) dropped."
        )

    def _slack_run(self) -> tuple[TaskRun, MagicMock]:
        user = User.objects.create(email="stream@example.com", distinct_id="stream-user")
        task = Task.objects.create(
            team=self.team,
            title="Artifact task",
            description="Write it up",
            origin_product=Task.OriginProduct.SLACK,
            created_by=user,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T123",
            channel="C1",
            thread_ts="1.0",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U1",
        )
        slack = MagicMock()
        slack.api_call.side_effect = lambda method, **_kwargs: {
            "canvases.create": {"canvas_id": "F900"},
            "files.getUploadURLExternal": {"upload_url": "https://files.slack.test/upload", "file_id": "F901"},
            "files.completeUploadExternal": {"files": [{"id": "F901", "title": "signups.csv"}]},
        }.get(method, {})
        slack_integration = MagicMock(client=slack)
        slack_integration.missing_scopes.return_value = set()
        return run, slack_integration

    def _canvas(self, run: TaskRun, slack_integration: MagicMock) -> TaskArtifact:
        return self._create(
            slack_integration,
            run=run,
            name="Daily active users",
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            content="# Daily active users",
        )

    def _chart(self, run: TaskRun, slack_integration: MagicMock) -> TaskArtifact:
        asset = ExportedAsset.objects.create(team=self.team, export_format=ExportedAsset.ExportFormat.PNG)
        return self._create(
            slack_integration,
            run=run,
            name="Signups by week.png",
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content_bytes=b"png-bytes",
            content_type="image/png",
            export_asset_id=asset.id,
        )

    def _spreadsheet(self, run: TaskRun, slack_integration: MagicMock) -> TaskArtifact:
        return self._create(
            slack_integration,
            run=run,
            name="signups.csv",
            artifact_type=TaskArtifact.ArtifactType.FILE,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            content="a,b\n1,2\n",
            content_type="text/csv",
        )

    def _create(self, slack_integration: MagicMock, **kwargs) -> TaskArtifact:
        with (
            patch(
                "products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping",
                return_value=slack_integration,
            ),
            patch("posthog.storage.object_storage.write"),
            patch("posthog.storage.object_storage.tag"),
        ):
            return create_living_artifact(**kwargs)

    @parameterized.expand(
        [
            # A canvas is written before delivery runs, so its card is a title and a link.
            ("canvas", "_canvas", ["section", "actions"]),
            # A chart's image block points at a PostHog-hosted url, so nothing is uploaded.
            ("chart_png", "_chart", ["section", "image"]),
            # A non-image file has no card: Slack shares it as its own message.
            ("csv_file", "_spreadsheet", []),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", return_value=True)
    def test_streamed_reply_delivers_each_kind_of_pending_artifact(
        self, _name, factory_name, expected_block_types, mock_stop
    ) -> None:
        # A streamed reply never reaches the relay activity, which used to be the only caller of
        # artifact delivery — so every canvas, chart and file produced under the agent-design flag
        # was staged and silently never posted.
        run, slack_integration = self._slack_run()
        artifact = getattr(self, factory_name)(run, slack_integration)

        with (
            patch(
                "products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping",
                return_value=slack_integration,
            ),
            patch(
                "products.tasks.backend.logic.services.living_artifacts.slack_message_exists",
                return_value=True,
            ),
            patch("posthog.storage.object_storage.read_bytes", return_value=b"payload"),
            patch("products.tasks.backend.logic.services.living_artifacts.requests.post"),
        ):
            stop_slack_agent_design_stream(
                StopSlackAgentDesignStreamInput(
                    slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                    ts="2.0",
                    final_markdown="Here it is.",
                    run_id=str(run.id),
                )
            )

        blocks = mock_stop.call_args.kwargs["artifact_blocks"] or []
        assert [block["type"] for block in blocks] == expected_block_types

        artifact.refresh_from_db()
        assert artifact.location["delivery_status"] == "delivered"

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", return_value=True)
    def test_streamed_canvas_card_carries_its_title_and_link(self, mock_stop) -> None:
        run, slack_integration = self._slack_run()
        self._canvas(run, slack_integration)

        with (
            patch(
                "products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping",
                return_value=slack_integration,
            ),
            patch(
                "products.tasks.backend.logic.services.living_artifacts.slack_message_exists",
                return_value=True,
            ),
        ):
            stop_slack_agent_design_stream(
                StopSlackAgentDesignStreamInput(
                    slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                    ts="2.0",
                    run_id=str(run.id),
                )
            )

        blocks = mock_stop.call_args.kwargs["artifact_blocks"]
        assert blocks[0]["text"]["text"] == "*Daily active users*"
        assert blocks[1]["elements"][0]["url"] == "https://app.slack.com/docs/T123/F900"

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", return_value=False)
    def test_artifacts_stay_pending_when_the_stream_rejects_their_blocks(self, _mock_stop) -> None:
        # Slack has to accept the blocks chunk for the cards to exist in the thread. Marking them
        # delivered on a rejected append would drop them from every later attempt.
        run, slack_integration = self._slack_run()
        artifact = self._canvas(run, slack_integration)

        with (
            patch(
                "products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping",
                return_value=slack_integration,
            ),
            patch(
                "products.tasks.backend.logic.services.living_artifacts.slack_message_exists",
                return_value=True,
            ),
            patch(
                "products.tasks.backend.logic.services.living_artifacts.deliver_pending_slack_artifacts"
            ) as mock_fallback,
        ):
            stop_slack_agent_design_stream(
                StopSlackAgentDesignStreamInput(
                    slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                    ts="2.0",
                    run_id=str(run.id),
                )
            )

        mock_fallback.assert_called_once()
        artifact.refresh_from_db()
        assert artifact.location["delivery_status"] == "pending"
