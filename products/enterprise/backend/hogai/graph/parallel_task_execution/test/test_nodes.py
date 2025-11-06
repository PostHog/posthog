import uuid
import asyncio
from typing import Any, cast

from unittest import TestCase
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig
from pydantic import ConfigDict

from posthog.schema import AssistantToolCall, TaskExecutionStatus

from products.enterprise.backend.hogai.graph.deep_research.types import DeepResearchNodeName
from products.enterprise.backend.hogai.graph.parallel_task_execution.nodes import (
    BaseTaskExecutorNode,
    TaskExecutionInputTuple,
)
from products.enterprise.backend.hogai.utils.types.base import BaseStateWithTasks, TaskArtifact, TaskResult
from products.enterprise.backend.hogai.utils.types.composed import MaxNodeName


class MockTestState(BaseStateWithTasks):
    """Mock state for testing the base class."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    test_input_tuples: list[TaskExecutionInputTuple] = []


class MockPartialTestState(BaseStateWithTasks):
    """Mock partial test state for testing the base class."""

    pass


class TaskExecutorNodeImplementation(BaseTaskExecutorNode[MockTestState, MockPartialTestState]):
    """Concrete implementation for testing the base class."""

    def __init__(self, team, user):
        super().__init__(team, user)
        self.input_tuples_called = False
        self.final_state_called = False

    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.TASK_EXECUTOR

    async def arun(self, state: MockTestState, config: RunnableConfig) -> MockPartialTestState:
        """Forward to the base _arun method."""
        self.state = state
        input_tuples = state.test_input_tuples
        tool_calls = [tool_call for tool_call, _, _ in input_tuples]
        return await self.aexecute(tool_calls, config)

    async def _aget_input_tuples(self, tool_calls: list[AssistantToolCall]) -> list[TaskExecutionInputTuple]:
        self.input_tuples_called = True
        # Return test input tuples based on state
        return self.state.test_input_tuples

    async def _aget_final_state(self, task_results: list[TaskResult]) -> MockPartialTestState:
        self.final_state_called = True
        return MockPartialTestState(task_results=task_results)


class TestBaseTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.node = TaskExecutorNodeImplementation(self.mock_team, self.mock_user)

    def _create_task(self, task_id: str | None = None) -> AssistantToolCall:
        return AssistantToolCall(
            id=task_id or str(uuid.uuid4()),
            name="test_tool",
            args={},
        )

    def _create_task_result(
        self, task_id: str, status: TaskExecutionStatus = TaskExecutionStatus.COMPLETED
    ) -> TaskResult:
        return TaskResult(
            id=task_id,
            result="Success",
            artifacts=[],
            status=status,
        )


class TestTaskExecution(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_single_task_execution(self, mock_write_message):
        """Test execution of a single task."""
        task = self._create_task("task1")

        async def task_coroutine(_: Any):
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        self.assertTrue(self.node.input_tuples_called)
        self.assertTrue(self.node.final_state_called)

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_multiple_tasks_parallel_execution(self, mock_write_message):
        """Test that multiple tasks are executed in parallel."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")
        task3 = self._create_task("task3")

        execution_order = []

        async def task1_coroutine(input_dict):
            await asyncio.sleep(0.1)
            execution_order.append("task1")
            return self._create_task_result("task1")

        async def task2_coroutine(input_dict):
            await asyncio.sleep(0.05)
            execution_order.append("task2")
            return self._create_task_result("task2")

        async def task3_coroutine(input_dict):
            execution_order.append("task3")
            return self._create_task_result("task3")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
            (task3, [], task3_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Tasks should complete in order of their execution time, not submission
        self.assertEqual(execution_order, ["task3", "task2", "task1"])


class TestReasoningCallback(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_reasoning_callback_for_single_task(self, mock_write_message):
        """Test that reasoning messages are sent for single task execution."""
        task = self._create_task("task1")

        async def task_coroutine(input_dict):
            # Simulate sending reasoning messages
            await self.node._reasoning_callback("task1", "Starting analysis")
            await self.node._reasoning_callback("task1", "Processing data")
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_reasoning_callback_for_multiple_tasks(self, mock_write_message):
        """Test that task execution messages are updated for multiple tasks."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task1_coroutine(input_dict):
            await self.node._reasoning_callback("task1", "Task 1 progress")
            return self._create_task_result("task1")

        async def task2_coroutine(input_dict):
            await self.node._reasoning_callback("task2", "Task 2 progress")
            return self._create_task_result("task2")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)


class TestErrorHandling(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.capture_exception")
    async def test_handles_task_failure(self, mock_capture):
        """Test that individual task failures are handled gracefully."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task1_coroutine(input_dict):
            raise ValueError("Task 1 failed")

        async def task2_coroutine(input_dict):
            return self._create_task_result("task2")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
        ]
        config = RunnableConfig()

        # Task 2 should still complete even if task 1 fails
        await self.node.arun(state, config)
        self.assertTrue(self.node.final_state_called)

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.capture_exception")
    async def test_handles_general_exception(self, mock_capture):
        """Test that general exceptions are captured and re-raised."""
        # Mock _aget_input_tuples to raise an exception
        with patch.object(self.node, "_aget_input_tuples") as mock_get_input:
            mock_get_input.side_effect = RuntimeError("General failure")

            state = MockTestState()
            config = RunnableConfig()

            with self.assertRaises(RuntimeError):
                await self.node.arun(state, config)

            mock_capture.assert_called_once()

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_cancels_remaining_tasks_on_exception(self, mock_write_message):
        """Test that remaining tasks are cancelled when an exception occurs."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        task2_started = asyncio.Event()
        task2_cancelled = False

        async def task1_coroutine(input_dict):
            await task2_started.wait()  # Wait for task2 to start
            raise RuntimeError("Critical failure")

        async def task2_coroutine(input_dict):
            nonlocal task2_cancelled
            task2_started.set()
            try:
                await asyncio.sleep(10)  # Long running task
                return self._create_task_result("task2")
            except asyncio.CancelledError:
                task2_cancelled = True
                raise

        # Mock _aget_final_state to raise an exception
        with patch.object(self.node, "_aget_final_state") as mock_final_state:
            mock_final_state.side_effect = RuntimeError("Critical failure in final state")

            state = MockTestState()
            state.test_input_tuples = [
                (task1, [], task1_coroutine),
                (task2, [], task2_coroutine),
            ]
            config = RunnableConfig()

            with self.assertRaises(RuntimeError):
                await self.node.arun(state, config)


class TestArtifactHandling(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_passes_artifacts_to_coroutines(self, mock_write_message):
        """Test that artifacts are passed correctly to task coroutines."""
        task = self._create_task("task1")
        input_artifact = TaskArtifact(id=None, task_id="input_artifact", content="Input artifact")

        received_artifacts = None

        async def task_coroutine(input_dict):
            nonlocal received_artifacts
            received_artifacts = input_dict.get("artifacts")
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [input_artifact], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        self.assertEqual(received_artifacts, [input_artifact])


class TestMessageFlow(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_no_task_execution_message_for_single_task(self, mock_write_message):
        """Test that no TaskExecutionMessage is sent for single task."""
        task = self._create_task("task1")

        async def task_coroutine(_: Any):
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_task_execution_messages_for_multiple_tasks(self, mock_write_message):
        """Test that TaskExecutionMessages are sent for multiple tasks."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task_coroutine(input_dict):
            task_id = input_dict["task"].id
            return self._create_task_result(task_id)

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task_coroutine),
            (task2, [], task_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)


class TestEdgeCases(TestBaseTaskExecutorNode):
    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_empty_input_tuples_raises_error(self, mock_write_message):
        """Test that empty input tuples raises ValueError."""
        state = MockTestState()
        state.test_input_tuples = []
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No input tuples provided")
        self.assertTrue(self.node.input_tuples_called)
        self.assertFalse(self.node.final_state_called)  # Should not reach final state

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_none_task_result(self, mock_write_message):
        """Test handling of None task results."""
        task = self._create_task("task1")

        async def task_coroutine(input_dict):
            return None  # Return None instead of TaskResult

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Should handle None gracefully
        self.assertTrue(self.node.final_state_called)


class TestDispatcherIntegration(TestBaseTaskExecutorNode):
    """Test dispatcher message flow in task execution."""

    async def test_dispatcher_sends_tool_call_messages(self):
        """Test that dispatcher sends AssistantToolCallMessage for each completed task."""
        from posthog.schema import AssistantToolCall

        task1 = AssistantToolCall(id="tool1", name="test_tool", args={}, type="tool_call")
        task2 = AssistantToolCall(id="tool2", name="test_tool", args={}, type="tool_call")

        async def task_coroutine(input_dict):
            task_id = input_dict["task_id"]
            return self._create_task_result(task_id)

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task_coroutine),
            (task2, [], task_coroutine),
        ]
        config = RunnableConfig()

        with patch.object(self.node, "dispatcher") as mock_dispatcher:
            await self.node.arun(state, config)

            # Verify dispatcher.message was called for each task result
            self.assertGreaterEqual(mock_dispatcher.message.call_count, 2)

    async def test_dispatcher_called_with_correct_tool_call_id(self):
        """Test that dispatcher messages include correct tool_call_id."""
        from posthog.schema import AssistantToolCall, AssistantToolCallMessage

        tool_call_id = "test_tool_123"
        task = AssistantToolCall(id=tool_call_id, name="test_tool", args={}, type="tool_call")

        async def task_coroutine(input_dict):
            return self._create_task_result(tool_call_id)

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        with patch.object(self.node, "dispatcher") as mock_dispatcher:
            await self.node.arun(state, config)

            # Find the call with AssistantToolCallMessage
            messages_sent = [call[0][0] for call in mock_dispatcher.message.call_args_list]
            tool_messages = [m for m in messages_sent if isinstance(m, AssistantToolCallMessage)]

            self.assertGreater(len(tool_messages), 0)
            self.assertEqual(tool_messages[0].tool_call_id, tool_call_id)


class TestPartialFailureScenarios(TestBaseTaskExecutorNode):
    """Test scenarios where some tasks fail but others succeed."""

    @patch("products.enterprise.backend.hogai.graph.parallel_task_execution.nodes.capture_exception")
    async def test_some_tasks_fail_others_succeed(self, mock_capture):
        """Test that when some tasks fail, successful tasks still complete."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")
        task3 = self._create_task("task3")

        async def task1_coroutine(input_dict):
            raise ValueError("Task 1 failed")

        async def task2_coroutine(input_dict):
            return self._create_task_result("task2")

        async def task3_coroutine(input_dict):
            raise RuntimeError("Task 3 failed")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
            (task3, [], task3_coroutine),
        ]
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        # Final state should be called even with partial failures
        self.assertTrue(self.node.final_state_called)
        # Only task2 should have succeeded
        self.assertEqual(len(result.task_results), 1)
        self.assertEqual(result.task_results[0].id, "task2")

    async def test_all_tasks_fail(self):
        """Test behavior when all tasks fail."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def failing_coroutine(input_dict):
            raise ValueError("Task failed")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], failing_coroutine),
            (task2, [], failing_coroutine),
        ]
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        # Should complete with empty results
        self.assertTrue(self.node.final_state_called)
        self.assertEqual(len(result.task_results), 0)


class TestConcurrentExecution(TestBaseTaskExecutorNode):
    """Test true parallel execution guarantees."""

    async def test_tasks_run_concurrently_not_sequentially(self):
        """Test that tasks genuinely run in parallel, not one after another."""
        import time

        task1 = self._create_task("task1")
        task2 = self._create_task("task2")
        task3 = self._create_task("task3")

        start_times = {}
        end_times = {}

        async def task_coroutine(input_dict):
            task_id = input_dict["task_id"]
            start_times[task_id] = time.time()
            await asyncio.sleep(0.1)  # All tasks take 0.1s
            end_times[task_id] = time.time()
            return self._create_task_result(task_id)

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task_coroutine),
            (task2, [], task_coroutine),
            (task3, [], task_coroutine),
        ]
        config = RunnableConfig()

        start = time.time()
        await self.node.arun(state, config)
        total_duration = time.time() - start

        # If sequential, would take ~0.3s. If parallel, should take ~0.1s
        self.assertLess(total_duration, 0.2, "Tasks should run in parallel, not sequentially")

        # All tasks should have overlapping execution times
        max_start = max(start_times.values())
        min_end = min(end_times.values())
        # Some overlap should exist
        self.assertLess(max_start, min_end, "Tasks should have overlapping execution")

    async def test_results_yielded_in_completion_order(self):
        """Test that results are yielded as they complete, not in submission order."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")
        task3 = self._create_task("task3")

        completion_order = []

        async def task1_coroutine(input_dict):
            await asyncio.sleep(0.15)
            completion_order.append("task1")
            return self._create_task_result("task1")

        async def task2_coroutine(input_dict):
            await asyncio.sleep(0.05)
            completion_order.append("task2")
            return self._create_task_result("task2")

        async def task3_coroutine(input_dict):
            await asyncio.sleep(0.10)
            completion_order.append("task3")
            return self._create_task_result("task3")

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
            (task3, [], task3_coroutine),
        ]
        config = RunnableConfig()

        with patch.object(self.node, "dispatcher"):
            await self.node.arun(state, config)

            # Verify completion order matches fastest-first
            self.assertEqual(completion_order, ["task2", "task3", "task1"])


class TestTaskDependencies(TestBaseTaskExecutorNode):
    """Test artifact dependency management between tasks."""

    async def test_artifacts_passed_to_dependent_tasks(self):
        """Test that artifacts from one task can be used by another."""
        task1 = self._create_task("task1")
        artifact_from_task1 = TaskArtifact(id=None, task_id="artifact1", content="Output from task1")

        task2 = self._create_task("task2")

        received_artifacts = None

        async def task1_coroutine(input_dict):
            result = self._create_task_result("task1")
            result.artifacts = [artifact_from_task1]
            return result

        async def task2_coroutine(input_dict):
            nonlocal received_artifacts
            received_artifacts = input_dict.get("artifacts")
            return self._create_task_result("task2")

        state = MockTestState()
        # task2 depends on task1's artifact
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [artifact_from_task1], task2_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Verify task2 received the artifact
        self.assertIsNotNone(received_artifacts)
        self.assertEqual(len(cast(list, received_artifacts)), 1)
        self.assertEqual(cast(list, received_artifacts)[0].task_id, "artifact1")

    async def test_multiple_artifacts_accumulated(self):
        """Test that multiple artifacts can be passed to a task."""
        task = self._create_task("task1")

        artifact1 = TaskArtifact(id=None, task_id="art1", content="First artifact")
        artifact2 = TaskArtifact(id=None, task_id="art2", content="Second artifact")
        artifact3 = TaskArtifact(id=None, task_id="art3", content="Third artifact")

        received_artifacts = None

        async def task_coroutine(input_dict):
            nonlocal received_artifacts
            received_artifacts = input_dict.get("artifacts")
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [
            (task, [artifact1, artifact2, artifact3], task_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        self.assertEqual(len(cast(list, received_artifacts)), 3)
        self.assertEqual([a.task_id for a in cast(list, received_artifacts)], ["art1", "art2", "art3"])
