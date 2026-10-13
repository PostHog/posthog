from typing import ClassVar

from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.slack_thread import SlackThreadHandler
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    StartSlackAgentDesignStreamInput,
    StopSlackAgentDesignStreamInput,
    start_slack_agent_design_stream,
    stop_slack_agent_design_stream,
)
from products.tasks.backend.temporal.process_task.utils import record_message_actor

PROJECT_URL = "https://us.posthog.com/project/7"


class TestStreamedAnswerCodeElements(SimpleTestCase):
    @parameterized.expand(
        [
            ("backticks", "```", True),
            ("tildes", "~~~", True),
            ("long_fence", "````", True),
            ("open_fence", "```", False),
        ]
    )
    @patch.object(SlackThreadHandler, "project_url", new_callable=PropertyMock, return_value=PROJECT_URL)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_code_elements_reach_slack_intact(
        self, _name: str, fence: str, closed: bool, mock_get_client: MagicMock, _project_url: PropertyMock
    ) -> None:
        # The final answer goes through the tag rewriter. A tag inside a fence stays literal,
        # so the example arrives as the agent typed it.
        client = mock_get_client.return_value
        context = {"integration_id": 1, "channel": "C001", "thread_ts": "1234.5678"}
        answer = f'Before\n\n{fence}xml\n<insight id="1">Example</insight>\n'
        if closed:
            answer += f"{fence}\n\nAfter\n"

        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(slack_thread_context=context, ts="1234.9999", final_markdown=answer)
        )

        streamed = "".join(
            chunk.get("text", "") for call in client.chat_appendStream.call_args_list for chunk in call.kwargs["chunks"]
        )
        assert streamed == answer


@override_settings(SITE_URL="https://us.posthog.com")
class TestSlackAgentDesignStream(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    integration: ClassVar[Integration]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.integration = Integration.objects.create(team=cls.team, kind="slack", integration_id="T123", config={})
        user = User.objects.create_and_join(cls.org, "creator@example.com", None)
        task = Task.objects.create(
            team=cls.team,
            title="Test task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=user,
        )
        cls.task_run = TaskRun.objects.create(
            task=task,
            team=cls.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"slack_actor_slack_user_id": "U456"},
        )

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream")
    def test_streamed_final_answer_links_object_elements(self, mock_stop) -> None:
        # Slack renders none of the tags, so dropping one takes the agent's own label with it.
        # The project comes from the thread's integration, so the link opens where the reader is.
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

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream", autospec=True)
    def test_closing_the_stream_hands_the_reply_the_turns_trace_id(self, mock_stop) -> None:
        # Closing the stream is what appends the thumbs, so a trace id dropped here leaves
        # every rating on a streamed answer with nothing to open.
        trace_id = "f960aead-b2af-4ee0-b0eb-630109a1b2a0"

        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                ts="2.0",
                final_markdown="Done.",
                trace_id=trace_id,
            )
        )

        assert mock_stop.call_args.args[0].turn_trace_id == trace_id

    @patch("products.tasks.backend.logic.services.living_artifacts.deliver_pending_slack_file_artifacts")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_a_stream_slack_closed_still_delivers_the_turns_attachments(self, mock_get_client, mock_deliver) -> None:
        client = mock_get_client.return_value
        client.chat_appendStream.side_effect = SlackApiError(
            "message_not_in_streaming_state", {"error": "message_not_in_streaming_state"}
        )

        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                ts="2.0",
                final_markdown="Signups grew.",
                run_id=str(self.task_run.id),
            )
        )

        assert "Signups grew." in client.chat_postMessage.call_args.kwargs["text"]
        mock_deliver.assert_called_once_with(self.task_run)

    @parameterized.expand(
        [
            ("run_actor", None, "U456"),
            # Another participant spoke after this message, so the run's actor is no longer its sender.
            ("message_sender", "msg-2", "U789"),
        ]
    )
    @patch(
        "products.slack_app.backend.slack_thread.SlackThreadHandler.start_status_stream",
        autospec=True,
        return_value="2.0",
    )
    def test_opening_the_stream_tags_the_turns_sender_not_the_thread_creator(
        self, _name, message_id, expected_target, mock_start
    ) -> None:
        record_message_actor(str(self.task_run.id), "msg-2", "U789")

        stream = start_slack_agent_design_stream(
            StartSlackAgentDesignStreamInput(
                slack_thread_context={
                    "integration_id": self.integration.id,
                    "channel": "C1",
                    "thread_ts": "1.0",
                    "mentioning_slack_user_id": "U123",
                },
                first_markdown_text="Done.",
                run_id=str(self.task_run.id),
                message_id=message_id,
            )
        )

        assert mock_start.call_args.args[0].actor_slack_user_id == expected_target
        assert stream is not None and stream.actor_slack_user_id == expected_target
