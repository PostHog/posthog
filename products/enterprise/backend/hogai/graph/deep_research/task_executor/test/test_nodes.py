import uuid
import asyncio
from typing import cast

from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    HumanMessage,
    TaskExecutionStatus,
    VisualizationMessage,
)

from products.enterprise.backend.hogai.graph.deep_research.task_executor.nodes import DeepResearchTaskExecutorNode
from products.enterprise.backend.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from products.enterprise.backend.hogai.utils.types.base import AssistantMessageUnion, InsightArtifact, TaskResult


class TestTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_team.name = "Test Team"
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.email = "test@example.com"

        self.node = DeepResearchTaskExecutorNode(self.mock_team, self.mock_user)

    def _create_insight_artifact(
        self,
        artifact_id: str | None = None,
        description: str = "Test artifact",
        query: str = "Test query",
    ) -> InsightArtifact:
        return InsightArtifact(
            task_id=artifact_id or str(uuid.uuid4()),
            id=None,
            content=description,
            query=AssistantHogQLQuery(query=query),
        )

    def _create_assistant_tool_call(self, tool_call_id: str = "test_tool_call") -> AssistantToolCall:
        return AssistantToolCall(
            id=tool_call_id,
            name="test_tool",
            args={"test": "args"},
        )

    def _create_assistant_message_with_tool_calls(
        self, tool_calls: list[AssistantToolCall] | None = None
    ) -> AssistantMessage:
        if not tool_calls:
            tool_calls = [self._create_assistant_tool_call("test_tool_call")]
        return AssistantMessage(content="Test message", tool_calls=tool_calls)

    def _create_state_with_assistant_message(
        self, tool_calls: list[AssistantToolCall] | None = None
    ) -> DeepResearchState:
        messages = [self._create_assistant_message_with_tool_calls(tool_calls)]
        return DeepResearchState(
            messages=messages,
        )


class TestTaskExecutorNodeInitialization(TestTaskExecutorNode):
    def test_node_initializes_correctly(self):
        """Test that DeepResearchTaskExecutorNode initializes correctly."""
        self.assertIsNotNone(self.node)
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)


class TestTaskExecutorNodeArun(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode.dispatcher")
    async def test_arun_with_valid_tool_call_and_tasks(self, mock_dispatcher):
        """Test successful execution with valid tool call message and tasks."""
        config = RunnableConfig()
        state = self._create_state_with_assistant_message()

        # Mock the insights graph execution
        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.return_value = TaskResult(
                id="test_tool_call",
                result="Task completed",
                artifacts=[self._create_insight_artifact()],
                status=TaskExecutionStatus.COMPLETED,
            )

            result = await self.node.arun(state, config)

            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(len(result.messages), 2)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)

    async def test_arun_raises_error_for_missing_tool_call_message(self):
        """Test that we raise ValueError when no tool call message is found."""
        state = DeepResearchState(
            messages=[HumanMessage(content="Test")],  # No AssistantMessage with tool_calls
        )
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No tool call message found")

    async def test_arun_raises_error_for_assistant_message_without_tool_calls(self):
        """Test that arun raises ValueError when AssistantMessage has no tool_calls."""
        state = DeepResearchState(
            messages=[AssistantMessage(content="Test message")],  # No tool_calls
        )
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No tool call message found")


class TestTaskExecutorInsightsExecution(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode.dispatcher")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsGraph")
    async def test_execute_task_with_insights_successful(self, mock_insights_graph_class, mock_dispatcher):
        """Test successful task execution through insights pipeline."""

        # Mock the insights graph
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        # Create a visualization message that will be extracted
        viz_message = VisualizationMessage(
            id="viz_1",
            answer=AssistantTrendsQuery(series=[]),
        )

        # Mock the async stream from insights graph
        async def mock_astream(*args, **kwargs):
            yield {("insights_graph", "viz_node"): {"messages": [viz_message]}}
            yield {
                ("insights_graph", "final"): {
                    "messages": [
                        AssistantToolCallMessage(
                            content="Insights generated successfully", tool_call_id="task_tool_call_id"
                        )
                    ]
                }
            }

        mock_graph.astream = mock_astream

        # Execute the task
        tool_call = self._create_assistant_tool_call()
        input_dict = {"task_id": "test_tool_call", "task": tool_call, "artifacts": [], "config": RunnableConfig()}

        result = await self.node._execute_create_insight(input_dict)

        self.assertIsInstance(result, TaskResult)
        self.assertIsNotNone(result)  # Ensure result is not None for mypy
        assert result is not None  # Type narrowing for mypy
        self.assertEqual(result.id, tool_call.id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.artifacts), 1)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode.dispatcher")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsGraph")
    async def test_execute_task_with_insights_no_artifacts(self, mock_insights_graph_class, mock_dispatcher):
        """Test task execution that produces no artifacts."""
        task = self._create_assistant_tool_call()

        # Mock the insights graph
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        # Mock stream with no visualization messages
        async def mock_astream(*args, **kwargs):
            yield {
                ("insights_graph", "final"): {
                    "messages": [
                        AssistantToolCallMessage(
                            content="No insights could be generated", tool_call_id="task_tool_call_id"
                        )
                    ]
                }
            }

        mock_graph.astream = mock_astream
        mock_graph.aget_reasoning_message_by_node_name = {}

        # Execute the task
        input_dict = {"task_id": task.id, "task": task, "artifacts": [], "config": RunnableConfig()}

        result = await self.node._execute_create_insight(input_dict)

        self.assertIsInstance(result, TaskResult)
        self.assertIsNotNone(result)  # Ensure result is not None for mypy
        assert result is not None  # Type narrowing for mypy
        self.assertEqual(result.id, task.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.artifacts), 0)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.capture_exception")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode.dispatcher")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsGraph")
    async def test_execute_task_with_exception(self, mock_insights_graph_class, mock_dispatcher, mock_capture):
        """Test task execution that encounters an exception."""
        task = self._create_assistant_tool_call()

        # Mock the insights graph to raise an exception
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        test_exception = Exception("Insights generation failed")

        async def mock_astream(*args, **kwargs):
            raise test_exception

        mock_graph.astream = mock_astream

        # Execute the task
        input_dict = {"task_id": task.id, "task": task, "artifacts": [], "config": RunnableConfig()}

        with self.assertRaises(Exception) as cm:
            await self.node._execute_create_insight(input_dict)

        self.assertEqual(str(cm.exception), "Insights generation failed")
        mock_capture.assert_called_once_with(test_exception)


class TestParallelTaskExecution(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode.dispatcher")
    async def test_multiple_tasks_executed_in_parallel(self, mock_dispatcher):
        """Test that multiple tasks are executed in parallel."""
        task1 = self._create_assistant_tool_call("task_1")
        task2 = self._create_assistant_tool_call("task_2")
        task3 = self._create_assistant_tool_call("task_3")

        state = self._create_assistant_message_with_tool_calls([task1, task2, task3])
        config = RunnableConfig()

        execution_order = []

        async def mock_execute_task1(input_dict):
            await asyncio.sleep(0.1)
            execution_order.append("task_1")
            return TaskResult(id="task_1", result="Result 1", artifacts=[], status=TaskExecutionStatus.COMPLETED)

        async def mock_execute_task2(input_dict):
            await asyncio.sleep(0.05)
            execution_order.append("task_2")
            return TaskResult(id="task_2", result="Result 2", artifacts=[], status=TaskExecutionStatus.COMPLETED)

        async def mock_execute_task3(input_dict):
            execution_order.append("task_3")
            return TaskResult(id="task_3", result="Result 3", artifacts=[], status=TaskExecutionStatus.COMPLETED)

        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.side_effect = [mock_execute_task3, mock_execute_task2, mock_execute_task1]

            result = await self.node.arun(cast(DeepResearchState, state), config)

            # Tasks should complete in order of execution time
            self.assertEqual(execution_order, ["task_3", "task_2", "task_1"])

            # Check final state
            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(len(result.task_results), 3)


class TestArtifactExtraction(TestTaskExecutorNode):
    def test_extract_artifacts_from_visualization_messages(self):
        """Test artifact extraction from visualization messages."""
        task = self._create_assistant_tool_call("task_1")

        viz_message = VisualizationMessage(id="viz_1", answer=AssistantTrendsQuery(series=[]))

        messages: list[AssistantMessageUnion] = [
            viz_message,
            AssistantToolCallMessage(content="Complete", tool_call_id="test"),
        ]

        artifacts = self.node._extract_artifacts(messages, task)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].task_id, "task_1")
        self.assertEqual(artifacts[0].content, "")
        self.assertEqual(artifacts[0].query.kind, "TrendsQuery")

    def test_extract_artifacts_handles_no_visualizations(self):
        """Test artifact extraction when no visualization messages exist."""
        task = self._create_assistant_tool_call()

        messages: list[AssistantMessageUnion] = [
            AssistantToolCallMessage(content="No data available", tool_call_id="test"),
        ]

        artifacts = self.node._extract_artifacts(messages, task)

        self.assertEqual(len(artifacts), 0)
