from typing import ClassVar

from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.helpers.slack_object_tags import split_incomplete_tag_suffix
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.slack_thread import SlackThreadHandler
from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    AppendSlackAgentDesignStepsInput,
    StopSlackAgentDesignStreamInput,
    append_slack_agent_design_steps,
    stop_slack_agent_design_stream,
)

PROJECT_URL = "https://us.posthog.com/project/7"


class TestBufferedSlackAgentDesignStream(SimpleTestCase):
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
    def test_buffered_code_elements_reach_slack_intact(
        self, _name: str, fence: str, closed: bool, mock_get_client: MagicMock, _project_url: PropertyMock
    ) -> None:
        # Goes through the activities, so the rewriter runs on every flush. A tag cut by a flush
        # boundary is held back and sent whole in the next one, and a tag inside a fence stays
        # literal, so the example arrives as the agent typed it.
        client = mock_get_client.return_value
        context = {"integration_id": 1, "channel": "C001", "thread_ts": "1234.5678"}
        updates = [f"Before\n\n{fence}xml\n", '<insight id="1">', "Example</insight>\n"]
        if closed:
            updates.append(f"{fence}\n\nAfter\n")
        pending = ""
        for update in updates:
            split = split_incomplete_tag_suffix(pending + update)
            pending = split.held
            if split.sendable:
                append_slack_agent_design_steps(
                    AppendSlackAgentDesignStepsInput(
                        slack_thread_context=context,
                        ts="1234.9999",
                        markdown_text=split.sendable,
                    )
                )
        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context=context,
                ts="1234.9999",
                final_markdown=pending,
            )
        )
        streamed = "".join(
            chunk.get("text", "") for call in client.chat_appendStream.call_args_list for chunk in call.kwargs["chunks"]
        )
        assert streamed == "".join(updates)


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
