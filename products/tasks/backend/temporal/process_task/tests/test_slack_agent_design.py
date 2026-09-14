from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase, override_settings

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    SLACK_STREAM_TS_STATE_KEY,
    AppendSlackAgentDesignStepsInput,
    StartSlackAgentDesignStreamInput,
    StopSlackAgentDesignStreamInput,
    StreamChunk,
    TaskUpdateChunk,
    append_slack_agent_design_steps,
    start_slack_agent_design_stream,
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

    def _slack_thread_context(self) -> dict:
        return {"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"}

    def _create_run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Stream task",
            description="",
            origin_product=Task.OriginProduct.SLACK,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.start_status_stream")
    def test_start_registers_the_open_stream_ts_and_stop_clears_it(self, mock_start, _mock_stop) -> None:
        # Artifact delivery reads this state key to append into the streamed message;
        # a start that doesn't register or a stop that doesn't clear strands it.
        run = self._create_run()
        mock_start.return_value = "42.1"

        ts = start_slack_agent_design_stream(
            StartSlackAgentDesignStreamInput(
                slack_thread_context=self._slack_thread_context(),
                first_markdown_text="Hello",
                run_id=str(run.id),
            )
        )
        assert ts == "42.1"
        run.refresh_from_db()
        assert run.state[SLACK_STREAM_TS_STATE_KEY] == "42.1"

        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context=self._slack_thread_context(),
                ts="42.1",
                run_id=str(run.id),
            )
        )
        run.refresh_from_db()
        assert SLACK_STREAM_TS_STATE_KEY not in run.state

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.append_stream_chunks")
    def test_ordered_chunks_keep_arrival_order_and_rewrite_object_tags(self, mock_append) -> None:
        append_slack_agent_design_steps(
            AppendSlackAgentDesignStepsInput(
                slack_thread_context=self._slack_thread_context(),
                ts="2.0",
                ordered_chunks=[
                    StreamChunk(markdown_text='See <insight id="9pQx3">the funnel</insight>.'),
                    StreamChunk(task_update=TaskUpdateChunk(id="t1", title="Read", status="in_progress")),
                    StreamChunk(markdown_text="Done."),
                ],
            )
        )

        chunks = mock_append.call_args.kwargs["chunks"]
        assert [c["type"] for c in chunks] == ["markdown_text", "task_update", "markdown_text"]
        assert chunks[0]["text"] == (
            f"See [the funnel](https://us.posthog.com/project/{self.team.id}/insights/9pQx3?unfurl=false)."
        )
        assert chunks[1]["title"] == "Read"
