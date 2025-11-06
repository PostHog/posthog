"""
Comprehensive tests for AssistantStreamProcessor.

Tests the stream processor logic that handles dispatcher actions,
routes messages based on node paths, and manages streaming state.
"""

from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest

from langchain_core.messages import AIMessageChunk

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    VisualizationItem,
    VisualizationMessage,
)

from products.enterprise.backend.hogai.utils.state import GraphValueUpdateTuple
from products.enterprise.backend.hogai.utils.stream_processor import AssistantStreamProcessor
from products.enterprise.backend.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantGraphName,
    AssistantNodeName,
    AssistantState,
    LangGraphUpdateEvent,
    MessageAction,
    MessageChunkAction,
    NodeEndAction,
    NodePath,
    NodeStartAction,
    UpdateAction,
)


class TestStreamProcessor(BaseTest):
    """Test the AssistantStreamProcessor logic in isolation."""

    def setUp(self):
        super().setUp()
        self.stream_processor = AssistantStreamProcessor(
            verbose_nodes={AssistantNodeName.ROOT, AssistantNodeName.TRENDS_GENERATOR},
            streaming_nodes={AssistantNodeName.TRENDS_GENERATOR},
            state_type=AssistantState,
        )

    def _create_dispatcher_event(
        self,
        action: MessageAction | NodeStartAction | MessageChunkAction | NodeEndAction | UpdateAction,
        node_name: AssistantNodeName = AssistantNodeName.ROOT,
        node_run_id: str = "test_run_id",
        node_path: tuple[NodePath, ...] | None = None,
    ) -> AssistantDispatcherEvent:
        """Helper to create a dispatcher event for testing."""
        return AssistantDispatcherEvent(
            action=action, node_name=node_name, node_run_id=node_run_id, node_path=node_path
        )

    # Node lifecycle tests

    def test_node_start_initializes_chunk_and_returns_ack(self):
        """Test NodeStartAction initializes a chunk for the run_id and returns ACK."""
        run_id = "test_run_123"
        event = self._create_dispatcher_event(NodeStartAction(), node_run_id=run_id)
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        first_result = result[0]
        self.assertIsInstance(first_result, AssistantGenerationStatusEvent)
        assert isinstance(first_result, AssistantGenerationStatusEvent)
        self.assertEqual(first_result.type, AssistantGenerationStatusType.ACK)
        self.assertIn(run_id, self.stream_processor._chunks)
        self.assertEqual(self.stream_processor._chunks[run_id].content, "")

    def test_node_end_cleans_up_chunk(self):
        """Test NodeEndAction removes the chunk for the run_id."""
        run_id = "test_run_456"
        self.stream_processor._chunks[run_id] = AIMessageChunk(content="test")

        state = AssistantState(messages=[])
        event = self._create_dispatcher_event(NodeEndAction(state=state), node_run_id=run_id)
        self.stream_processor.process(event)

        self.assertNotIn(run_id, self.stream_processor._chunks)

    def test_node_end_processes_messages_from_state(self):
        """Test NodeEndAction processes all messages from the final state."""
        run_id = "test_run_789"
        message1 = AssistantMessage(id=str(uuid4()), content="Message 1")
        message2 = AssistantMessage(id=str(uuid4()), content="Message 2")
        state = AssistantState(messages=[message1, message2])

        event = self._create_dispatcher_event(
            NodeEndAction(state=state), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        results = self.stream_processor.process(event)

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], message1)
        self.assertEqual(results[1], message2)

    # Message streaming tests

    def test_message_chunk_streaming_for_streaming_nodes(self):
        """Test MessageChunkAction streams chunks for nodes in streaming_nodes."""
        run_id = "stream_run_1"
        chunk = AIMessageChunk(content="Hello ")

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "Hello ")
        self.assertIsNone(result[0].id)

    def test_message_chunk_ignored_for_non_streaming_nodes(self):
        """Test MessageChunkAction returns None for nodes not in streaming_nodes."""
        run_id = "stream_run_2"
        chunk = AIMessageChunk(content="Hello ")

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_multiple_chunks_merged_correctly(self):
        """Test that multiple MessageChunkActions are merged correctly."""
        run_id = "stream_run_3"

        chunk1 = AIMessageChunk(content="Hello ")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result1 = self.stream_processor.process(event1)

        chunk2 = AIMessageChunk(content="world!")
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result2 = self.stream_processor.process(event2)

        self.assertIsNotNone(result1)
        assert result1 is not None
        assert isinstance(result1[0], AssistantMessage)
        self.assertEqual(result1[0].content, "Hello ")
        self.assertIsNotNone(result2)
        assert result2 is not None
        assert isinstance(result2[0], AssistantMessage)
        self.assertEqual(result2[0].content, "Hello world!")

    def test_concurrent_chunks_from_different_runs(self):
        """Test that chunks from different node runs are kept separate."""
        run_id_1 = "stream_run_4a"
        run_id_2 = "stream_run_4b"

        chunk1 = AIMessageChunk(content="Run 1")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id_1
        )
        self.stream_processor.process(event1)

        chunk2 = AIMessageChunk(content="Run 2")
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id_2
        )
        self.stream_processor.process(event2)

        self.assertEqual(self.stream_processor._chunks[run_id_1].content, "Run 1")
        self.assertEqual(self.stream_processor._chunks[run_id_2].content, "Run 2")

    def test_handles_mixed_content_types_in_chunks(self):
        """Test that stream processor handles switching between string and list content formats."""
        run_id = "stream_run_5"

        # Start with string content
        chunk1 = AIMessageChunk(content="initial string")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        self.stream_processor.process(event1)

        # Switch to list format (OpenAI Responses API)
        chunk2 = AIMessageChunk(content=[{"type": "text", "text": "list content"}])
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result = self.stream_processor.process(event2)

        # The result should normalize to string content
        self.assertIsNotNone(result)
        assert result is not None
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "list content")

    # Root vs nested message handling tests

    def test_root_message_from_verbose_node_returned(self):
        """Test messages from root level (node_path <= 2) in verbose nodes are returned."""
        message = AssistantMessage(id=str(uuid4()), content="Root message")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    def test_root_message_from_non_verbose_node_filtered(self):
        """Test messages from root level in non-verbose nodes are filtered out."""
        message = AssistantMessage(id=str(uuid4()), content="Non-verbose message")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.BILLING))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.BILLING, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_nested_visualization_message_returned(self):
        """Test VisualizationMessage from nested node/graph is returned."""
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")

        # Create a deep node path indicating this is from a nested graph
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], viz_message)

    def test_nested_multi_visualization_message_returned(self):
        """Test MultiVisualizationMessage from nested node/graph is returned."""
        query = TrendsQuery(series=[])
        viz_item = VisualizationItem(query="test query", answer=query, plan="test plan")
        multi_viz_message = MultiVisualizationMessage(visualizations=[viz_item])

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=multi_viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], multi_viz_message)

    def test_nested_notebook_message_returned(self):
        """Test NotebookUpdateMessage from nested node/graph is returned."""
        content = ProsemirrorJSONContent(type="doc", content=[])
        notebook_message = NotebookUpdateMessage(notebook_id="nb123", content=content)

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=notebook_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], notebook_message)

    def test_nested_failure_message_returned(self):
        """Test FailureMessage from nested node/graph is returned."""
        failure_message = FailureMessage(content="Something went wrong")

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=failure_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], failure_message)

    def test_nested_tool_call_message_filtered(self):
        """Test AssistantToolCallMessage from nested node/graph is filtered out."""
        tool_call_message = AssistantToolCallMessage(content="Tool result", tool_call_id=str(uuid4()))

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=tool_call_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_short_node_path_treated_as_root(self):
        """Test that node_path with length <= 2 is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="Short path message")

        # Path with just 2 elements (graph + node)
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    # UpdateAction tests

    def test_update_action_creates_update_event_with_parent_from_path(self):
        """Test UpdateAction creates AssistantUpdateEvent using closest tool_call_id from node_path."""
        message_id = str(uuid4())
        tool_call_id = str(uuid4())

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=message_id, tool_call_id=tool_call_id),
            NodePath(name=AssistantGraphName.INSIGHTS),
        )

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantUpdateEvent)
        update_event = cast(AssistantUpdateEvent, result[0])
        self.assertEqual(update_event.id, message_id)
        self.assertEqual(update_event.tool_call_id, tool_call_id)
        self.assertEqual(update_event.content, "Update content")

    def test_update_action_without_parent_returns_none(self):
        """Test UpdateAction without parent tool_call_id in node_path returns None."""
        # No tool_call_id in any path element
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_update_action_without_node_path_returns_none(self):
        """Test UpdateAction without node_path returns None."""
        event = self._create_dispatcher_event(UpdateAction(content="Update content"), node_path=None)
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_update_action_finds_closest_tool_call_in_reversed_path(self):
        """Test UpdateAction finds the closest (most recent) tool_call_id by reversing the path."""
        # Multiple tool calls in the path - should find the closest one (last in reversed iteration)
        message_id_1 = str(uuid4())
        tool_call_id_1 = str(uuid4())
        message_id_2 = str(uuid4())
        tool_call_id_2 = str(uuid4())

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=message_id_1, tool_call_id=tool_call_id_1),
            NodePath(name=AssistantGraphName.INSIGHTS, message_id=message_id_2, tool_call_id=tool_call_id_2),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        update_event = cast(AssistantUpdateEvent, result[0])
        # Should use the closest parent (last one in reversed path)
        self.assertEqual(update_event.id, message_id_2)
        self.assertEqual(update_event.tool_call_id, tool_call_id_2)

    # Message deduplication tests

    def test_messages_with_id_deduplicated(self):
        """Test that messages with the same ID are deduplicated."""
        message_id = str(uuid4())
        message1 = AssistantMessage(id=message_id, content="First occurrence")
        message2 = AssistantMessage(id=message_id, content="Second occurrence")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        # Process first message - should be returned
        event1 = self._create_dispatcher_event(
            MessageAction(message=message1), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result1 = self.stream_processor.process(event1)
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertEqual(result1[0], message1)

        # Process second message with same ID - should be filtered
        event2 = self._create_dispatcher_event(
            MessageAction(message=message2), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result2 = self.stream_processor.process(event2)
        self.assertIsNone(result2)

    def test_messages_without_id_not_deduplicated(self):
        """Test that messages without ID are always yielded (not deduplicated)."""
        message1 = AssistantMessage(content="Message without ID")
        message2 = AssistantMessage(content="Another message without ID")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event1 = self._create_dispatcher_event(
            MessageAction(message=message1), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result1 = self.stream_processor.process(event1)
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertEqual(result1[0], message1)

        event2 = self._create_dispatcher_event(
            MessageAction(message=message2), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result2 = self.stream_processor.process(event2)
        self.assertIsNotNone(result2)
        assert result2 is not None
        self.assertEqual(result2[0], message2)

    def test_preexisting_message_ids_filtered(self):
        """Test that stream processor filters messages with IDs already in _streamed_update_ids."""
        message_id = str(uuid4())

        # Pre-populate the streamed IDs
        self.stream_processor._streamed_update_ids.add(message_id)

        message = AssistantMessage(id=message_id, content="Already seen")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    # LangGraph update processing tests

    def test_langgraph_message_chunk_processed(self):
        """Test that LangGraph message chunk updates are converted and processed."""
        chunk = AIMessageChunk(content="LangGraph chunk")
        state = {"langgraph_node": AssistantNodeName.TRENDS_GENERATOR, "langgraph_checkpoint_ns": "checkpoint_123"}

        update = ["messages", (chunk, state)]
        event = LangGraphUpdateEvent(update=update)

        result = self.stream_processor.process_langgraph_update(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "LangGraph chunk")

    def test_langgraph_state_update_stored(self):
        """Test that LangGraph state updates are stored in _state."""
        new_state_dict = {"messages": [], "plan": "Test plan"}
        update = cast(GraphValueUpdateTuple, ["values", new_state_dict])

        event = LangGraphUpdateEvent(update=update)
        result = self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)
        self.assertIsNotNone(self.stream_processor._state)
        assert self.stream_processor._state is not None
        self.assertEqual(self.stream_processor._state.plan, "Test plan")

    def test_langgraph_non_message_chunk_ignored(self):
        """Test that LangGraph updates that are not AIMessageChunk are ignored."""
        regular_message = AssistantMessage(content="Not a chunk")
        state = {"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "checkpoint_456"}

        update = ["messages", (regular_message, state)]
        event = LangGraphUpdateEvent(update=update)

        result = self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)

    def test_langgraph_invalid_update_format_ignored(self):
        """Test that invalid LangGraph update formats are ignored."""
        update = "invalid_format"
        event = LangGraphUpdateEvent(update=update)

        result = self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)

    # Edge cases and error conditions

    def test_empty_node_path_treated_as_root(self):
        """Test that empty node_path is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="Empty path message")

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=()
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    def test_none_node_path_treated_as_root(self):
        """Test that None node_path is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="None path message")

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=None
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    def test_node_end_with_none_state_returns_none(self):
        """Test NodeEndAction with None state returns None."""
        event = self._create_dispatcher_event(NodeEndAction(state=None))
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_update_action_with_empty_content_returns_none(self):
        """Test UpdateAction with empty content returns None."""
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
        )

        event = self._create_dispatcher_event(UpdateAction(content=""), node_path=node_path)
        result = self.stream_processor.process(event)

        self.assertIsNone(result)

    def test_special_messages_from_root_level_returned(self):
        """Test that special message types from root level are handled by root message logic."""
        # VisualizationMessage from root should be returned if from verbose node
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test", answer=query, plan="plan")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.TRENDS_GENERATOR))

        event = self._create_dispatcher_event(
            MessageAction(message=viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], viz_message)
