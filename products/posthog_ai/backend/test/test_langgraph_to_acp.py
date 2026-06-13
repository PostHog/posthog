from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    PlanningStep,
    PlanningStepStatus,
    ProsemirrorJSONContent,
    ReasoningMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
    VisualizationItem,
    VisualizationMessage,
)

from products.posthog_ai.backend.langgraph_to_acp import (
    METHOD_SESSION_UPDATE,
    METHOD_USER_MESSAGE,
    messages_to_acp_frames,
)

from ee.hogai.utils.types.base import ArtifactRefMessage


def _session_update(frame: dict) -> dict:
    return frame["notification"]["params"]["update"]


class TestLangGraphToAcp(SimpleTestCase):
    def test_human_message_maps_to_user_message(self):
        frames = messages_to_acp_frames([HumanMessage(content="Why did checkout drop?")])

        assert len(frames) == 1
        assert frames[0]["type"] == "notification"
        assert frames[0]["notification"]["method"] == METHOD_USER_MESSAGE
        assert frames[0]["notification"]["params"]["content"] == "Why did checkout drop?"

    def test_plain_assistant_message_maps_to_agent_message(self):
        frames = messages_to_acp_frames([AssistantMessage(content="Here's the answer.", id="m1")])

        assert len(frames) == 1
        assert frames[0]["notification"]["method"] == METHOD_SESSION_UPDATE
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "agent_message"
        assert update["content"]["text"] == "Here's the answer."
        assert update["messageId"] == "m1"

    def test_assistant_message_with_tool_calls_maps_to_tool_call_frames(self):
        message = AssistantMessage(
            content="Let me check.",
            id="m2",
            tool_calls=[
                AssistantToolCall(id="tc1", name="query_runner", args={"q": "select 1"}),
                AssistantToolCall(id="tc2", name="create_insight", args={"name": "Funnel"}),
            ],
        )
        frames = messages_to_acp_frames([message])

        # One agent_message (the prose) plus one tool_call per call, in order.
        assert len(frames) == 3
        assert _session_update(frames[0])["sessionUpdate"] == "agent_message"
        first_tool = _session_update(frames[1])
        assert first_tool["sessionUpdate"] == "tool_call"
        assert first_tool["toolCallId"] == "tc1"
        assert first_tool["toolName"] == "query_runner"
        assert first_tool["input"] == {"q": "select 1"}
        assert _session_update(frames[2])["toolCallId"] == "tc2"

    def test_assistant_message_with_only_tool_calls_emits_no_text_frame(self):
        message = AssistantMessage(
            content="",
            id="m3",
            tool_calls=[AssistantToolCall(id="tc1", name="t", args={})],
        )
        frames = messages_to_acp_frames([message])

        assert len(frames) == 1
        assert _session_update(frames[0])["sessionUpdate"] == "tool_call"

    def test_tool_call_message_maps_to_tool_call_update(self):
        message = AssistantToolCallMessage(
            content="42 rows returned",
            tool_call_id="tc1",
            ui_payload={"dropped": "this"},
        )
        frames = messages_to_acp_frames([message])

        assert len(frames) == 1
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "tool_call_update"
        assert update["toolCallId"] == "tc1"
        assert update["status"] == "completed"
        assert update["rawOutput"] == "42 rows returned"
        # ui_payload has no ACP equivalent and is dropped.
        assert "ui_payload" not in update
        assert "this" not in str(update)

    def test_visualization_message_degrades_to_tool_call_update(self):
        message = VisualizationMessage(
            answer=AssistantHogQLQuery(query="select 1"),
            id="v1",
            plan="the plan",
            query="select 1",
        )
        frames = messages_to_acp_frames([message])

        assert len(frames) == 1
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "tool_call_update"
        assert update["toolCallId"] == "viz_v1"
        assert "select 1" in update["rawOutput"]

    def test_multi_visualization_message_degrades_to_tool_call_update(self):
        message = MultiVisualizationMessage(
            id="mv1",
            commentary="two charts",
            visualizations=[
                VisualizationItem(answer=AssistantHogQLQuery(query="select 1"), query="select 1"),
            ],
        )
        frames = messages_to_acp_frames([message])

        assert len(frames) == 1
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "tool_call_update"
        assert update["toolCallId"] == "multiviz_mv1"
        assert "two charts" in update["rawOutput"]

    def test_notebook_message_degrades_to_agent_message(self):
        message = NotebookUpdateMessage(
            content=ProsemirrorJSONContent(type="doc"),
            notebook_id="nb1",
            id="n1",
        )
        frames = messages_to_acp_frames([message])

        assert len(frames) == 1
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "agent_message"
        assert "nb1" in update["content"]["text"]

    def test_failure_message_maps_to_agent_message(self):
        frames = messages_to_acp_frames([FailureMessage(content="It broke", id="f1")])

        assert len(frames) == 1
        update = _session_update(frames[0])
        assert update["sessionUpdate"] == "agent_message"
        assert update["content"]["text"] == "It broke"

    def test_reasoning_message_maps_to_agent_message(self):
        frames = messages_to_acp_frames([ReasoningMessage(content="thinking...", id="r1")])

        assert len(frames) == 1
        assert _session_update(frames[0])["sessionUpdate"] == "agent_message"

    @parameterized.expand(
        [
            ("context", ContextMessage(content="system context")),
            ("planning", PlanningMessage(steps=[PlanningStep(description="x", status=PlanningStepStatus.PENDING)])),
            (
                "task_execution",
                TaskExecutionMessage(
                    tasks=[
                        TaskExecutionItem(
                            id="t1",
                            description="d",
                            prompt="p",
                            status=TaskExecutionStatus.PENDING,
                            task_type="generic",
                        )
                    ]
                ),
            ),
            ("artifact_ref", ArtifactRefMessage(content_type="visualization", artifact_id="a1", source="insight")),
        ]
    )
    def test_dropped_message_types_emit_no_frames(self, _name, message):
        assert messages_to_acp_frames([message]) == []

    @parameterized.expand(
        [
            ("human", HumanMessage(content="hi")),
            ("assistant", AssistantMessage(content="hello", id="a")),
            (
                "assistant_with_tools",
                AssistantMessage(content="x", id="b", tool_calls=[AssistantToolCall(id="t", name="n", args={})]),
            ),
            ("tool_result", AssistantToolCallMessage(content="out", tool_call_id="t")),
            ("visualization", VisualizationMessage(answer=AssistantHogQLQuery(query="q"), id="v")),
            ("failure", FailureMessage(content="err", id="f")),
            ("reasoning", ReasoningMessage(content="r", id="rid")),
        ]
    )
    def test_never_emits_agent_message_chunk(self, _name, message):
        frames = messages_to_acp_frames([message])
        for frame in frames:
            params = frame["notification"]["params"]
            update = params.get("update")
            if isinstance(update, dict):
                assert update.get("sessionUpdate") != "agent_message_chunk"

    def test_full_conversation_preserves_order(self):
        messages = [
            HumanMessage(content="q1"),
            AssistantMessage(content="a1", id="m1"),
            ContextMessage(content="ignored"),
            HumanMessage(content="q2"),
            AssistantMessage(
                content="checking",
                id="m2",
                tool_calls=[AssistantToolCall(id="tc1", name="query", args={})],
            ),
            AssistantToolCallMessage(content="result", tool_call_id="tc1"),
        ]
        frames = messages_to_acp_frames(messages)

        methods = [f["notification"]["method"] for f in frames]
        # Two user messages, two agent messages, one tool_call, one tool_call_update; context dropped.
        assert methods == [
            METHOD_USER_MESSAGE,
            METHOD_SESSION_UPDATE,
            METHOD_USER_MESSAGE,
            METHOD_SESSION_UPDATE,
            METHOD_SESSION_UPDATE,
            METHOD_SESSION_UPDATE,
        ]
