from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import AssistantMessage

from products.enterprise.backend.hogai.context.context import AssistantContextManager
from products.enterprise.backend.hogai.graph.root.tools.session_summarization import SessionSummarizationTool
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import NodePath


class TestSessionSummarizationTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = SessionSummarizationTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_execute_calls_session_summarization_node(self):
        mock_node_instance = MagicMock()
        mock_result = PartialAssistantState(
            messages=[AssistantMessage(content="Session summary: 10 sessions analyzed with 5 key patterns found")]
        )

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode", return_value=mock_node_instance):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda") as mock_runnable:
                mock_chain = MagicMock()
                mock_chain.ainvoke = AsyncMock(return_value=mock_result)
                mock_runnable.return_value = mock_chain

                result, artifact = await self.tool._arun_impl(
                    session_summarization_query="summarize all sessions from yesterday",
                    should_use_current_filters=False,
                    summary_title="All sessions from yesterday",
                    session_summarization_limit=-1,
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)
                assert artifact is not None
                self.assertEqual(len(artifact.messages), 1)
                message = cast(AssistantMessage, artifact.messages[0])
                self.assertEqual(message.content, "Session summary: 10 sessions analyzed with 5 key patterns found")

    async def test_execute_updates_state_with_all_parameters(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test response")])

        async def mock_ainvoke(state):
            self.assertEqual(state.session_summarization_query, "analyze mobile user sessions")
            self.assertEqual(state.should_use_current_filters, True)
            self.assertEqual(state.summary_title, "Mobile user sessions")
            self.assertEqual(state.root_tool_call_id, self.tool_call_id)
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                await self.tool._arun_impl(
                    session_summarization_query="analyze mobile user sessions",
                    should_use_current_filters=True,
                    summary_title="Mobile user sessions",
                    session_summarization_limit=-1,
                )

    async def test_execute_with_should_use_current_filters_false(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test response")])

        async def mock_ainvoke(state):
            self.assertEqual(state.should_use_current_filters, False)
            self.assertEqual(state.session_summarization_query, "watch last 300 session recordings")
            self.assertEqual(state.summary_title, "Last 300 sessions")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                await self.tool._arun_impl(
                    session_summarization_query="watch last 300 session recordings",
                    should_use_current_filters=False,
                    summary_title="Last 300 sessions",
                    session_summarization_limit=300,
                )

    async def test_execute_returns_failure_message_when_result_is_none(self):
        async def mock_ainvoke(state):
            return None

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    session_summarization_query="test query",
                    should_use_current_filters=False,
                    summary_title="Test",
                    session_summarization_limit=-1,
                )

                self.assertEqual(result, "Session summarization failed")
                self.assertIsNone(artifact)

    async def test_execute_returns_failure_message_when_result_has_no_messages(self):
        mock_result = PartialAssistantState(messages=[])

        async def mock_ainvoke(state):
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    session_summarization_query="test query",
                    should_use_current_filters=False,
                    summary_title="Test",
                    session_summarization_limit=-1,
                )

                self.assertEqual(result, "Session summarization failed")
                self.assertIsNone(artifact)

    async def test_execute_with_empty_summary_title(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Summary completed")])

        async def mock_ainvoke(state):
            self.assertEqual(state.summary_title, "")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    session_summarization_query="summarize sessions",
                    should_use_current_filters=False,
                    summary_title="",
                    session_summarization_limit=-1,
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)

    async def test_execute_preserves_original_state(self):
        """Test that the original state is not modified when creating the copied state"""
        original_query = "original query"
        original_state = AssistantState(
            messages=[],
            root_tool_call_id=self.tool_call_id,
            session_summarization_query=original_query,
        )

        tool = SessionSummarizationTool(
            team=self.team,
            user=self.user,
            state=original_state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test")])

        async def mock_ainvoke(state):
            # Verify the new state has updated values
            self.assertEqual(state.session_summarization_query, "new query")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.session_summaries.nodes.SessionSummarizationNode"):
            with patch("ee.hogai.graph.root.tools.session_summarization.RunnableLambda", return_value=mock_chain):
                await tool._arun_impl(
                    session_summarization_query="new query",
                    should_use_current_filters=True,
                    summary_title="New Summary",
                    session_summarization_limit=-1,
                )

        # Verify original state was not modified
        self.assertEqual(original_state.session_summarization_query, original_query)
        self.assertEqual(original_state.root_tool_call_id, self.tool_call_id)
