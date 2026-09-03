from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

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

    def _slack_run_with_canvas(self) -> tuple[TaskRun, TaskArtifact, MagicMock]:
        user = User.objects.create(email="stream@example.com", distinct_id="stream-user")
        task = Task.objects.create(
            team=self.team,
            title="Canvas task",
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
        slack.api_call.return_value = {"canvas_id": "F900"}
        slack_integration = MagicMock(client=slack)
        slack_integration.missing_scopes.return_value = set()
        with patch(
            "products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping",
            return_value=slack_integration,
        ):
            artifact = create_living_artifact(
                run=run,
                name="Daily active users",
                artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
                content="# Daily active users",
            )
        return run, artifact, slack_integration

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", return_value=True)
    def test_streamed_reply_delivers_the_runs_pending_artifacts(self, mock_stop) -> None:
        # A streamed reply never reaches the relay activity, which used to be the only caller of
        # artifact delivery — so every chart and canvas produced under the agent-design flag was
        # staged and silently never posted.
        run, artifact, slack_integration = self._slack_run_with_canvas()

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
                    final_markdown="Here it is.",
                    run_id=str(run.id),
                )
            )

        blocks = mock_stop.call_args.kwargs["artifact_blocks"]
        assert [block["type"] for block in blocks] == ["section", "actions"]
        assert blocks[0]["text"]["text"] == "*Daily active users*"
        assert blocks[1]["elements"][0]["url"] == "https://app.slack.com/docs/T123/F900"

        artifact.refresh_from_db()
        assert artifact.location["delivery_status"] == "delivered"

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", return_value=False)
    def test_artifacts_stay_pending_when_the_stream_rejects_their_blocks(self, _mock_stop) -> None:
        # Slack has to accept the blocks chunk for the cards to exist in the thread. Marking them
        # delivered on a rejected append would drop them from every later attempt.
        run, artifact, slack_integration = self._slack_run_with_canvas()

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
