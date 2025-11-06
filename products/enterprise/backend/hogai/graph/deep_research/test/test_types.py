from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import AssistantMessage, AssistantTrendsQuery, DeepResearchNotebook, DeepResearchType, HumanMessage

from products.enterprise.backend.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchState,
    PartialDeepResearchState,
    TodoItem,
    _SharedDeepResearchState,
)
from products.enterprise.backend.hogai.utils.types.base import InsightArtifact, TaskResult

"""
Test suite for type system consistency across multi-node deep research workflow.
"""


class TestTodoItem(BaseTest):
    """Test TodoItem class validation and initialization."""

    @parameterized.expand(
        [
            ("pending", "low"),
            ("in_progress", "medium"),
            ("completed", "high"),
        ]
    )
    def test_valid_todo_creation(self, status, priority):
        """Should create valid todo with all required fields."""
        todo = TodoItem(id="1", content="Test task", status=status, priority=priority)

        self.assertEqual(todo.id, "1")
        self.assertEqual(todo.content, "Test task")
        self.assertEqual(todo.status, status)
        self.assertEqual(todo.priority, priority)

    def test_todo_with_all_valid_statuses(self):
        """Should accept all valid PlanningStepStatus values."""
        for status in ["pending", "in_progress", "completed"]:
            todo = TodoItem(id="1", content="Test", status=status, priority="medium")
            self.assertEqual(todo.status, status)

    def test_todo_with_all_valid_priorities(self):
        """Should accept all valid priority values."""
        for priority in ["low", "medium", "high"]:
            todo = TodoItem(id="1", content="Test", status="pending", priority=priority)
            self.assertEqual(todo.priority, priority)

    @parameterized.expand(
        [
            ("invalid_status", "medium"),
            ("pending", "invalid_priority"),
            ("invalid", "invalid"),
        ]
    )
    def test_invalid_todo_fields(self, status, priority):
        """Should raise ValidationError for invalid status or priority."""
        with self.assertRaises(ValidationError):
            TodoItem(id="1", content="Test", status=status, priority=priority)

    def test_todo_serialization(self):
        """Should serialize and deserialize correctly."""
        original = TodoItem(
            id="42",
            content="Complex task with special chars: !@#$%",
            status="in_progress",
            priority="high",
        )

        serialized = original.model_dump()
        deserialized = TodoItem.model_validate(serialized)

        self.assertEqual(original.id, deserialized.id)
        self.assertEqual(original.content, deserialized.content)
        self.assertEqual(original.status, deserialized.status)
        self.assertEqual(original.priority, deserialized.priority)


class TestTaskResult(BaseTest):
    """Test TaskResult class with different configurations."""

    def test_task_result_with_default_artifacts(self):
        """Should create task result with empty artifacts list by default."""
        result = TaskResult(id="task-1", result="Task completed successfully", status="completed")

        self.assertEqual(result.id, "task-1")
        self.assertEqual(result.result, "Task completed successfully")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.artifacts, [])

    def test_task_result_with_artifacts(self):
        """Should create task result with artifacts."""
        mock_query = Mock(spec=AssistantTrendsQuery)
        artifact = InsightArtifact(id=None, task_id="artifact-1", query=mock_query, content="Test artifact")

        result = TaskResult(
            id="task-1",
            result="Task completed",
            status="completed",
            artifacts=[artifact],
        )

        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].task_id, "artifact-1")

    @parameterized.expand(
        [
            ("completed",),
            ("failed",),
        ]
    )
    def test_task_result_valid_statuses(self, status):
        """Should accept all valid TaskExecutionStatus values."""
        result = TaskResult(id="task-1", result="Result", status=status)
        self.assertEqual(result.status, status)

    def test_task_result_invalid_status(self):
        """Should raise ValidationError for invalid status."""
        with self.assertRaises(ValidationError):
            TaskResult(id="task-1", result="Result", status="invalid_status")

    def test_task_result_serialization(self):
        """Should serialize and deserialize correctly."""
        original = TaskResult(
            id="task-complex-123",
            result="Multi-line\nresult with\nspecial chars: !@#$%",
            status="failed",
            artifacts=[],
        )

        serialized = original.model_dump()
        deserialized = TaskResult.model_validate(serialized)

        self.assertEqual(original.id, deserialized.id)
        self.assertEqual(original.result, deserialized.result)
        self.assertEqual(original.status, deserialized.status)
        self.assertEqual(original.artifacts, deserialized.artifacts)


class TestDeepResearchIntermediateResult(BaseTest):
    """Test DeepResearchIntermediateResult class validation."""

    def test_intermediate_result_with_default_artifact_ids(self):
        """Should create intermediate result with empty artifact_ids by default."""
        result = DeepResearchIntermediateResult(content="Test content")

        self.assertEqual(result.content, "Test content")
        self.assertEqual(result.artifact_ids, [])

    def test_intermediate_result_with_artifact_ids(self):
        """Should create intermediate result with artifact IDs."""
        artifact_ids = ["artifact-1", "artifact-2", "artifact-3"]
        result = DeepResearchIntermediateResult(content="Content with artifacts", artifact_ids=artifact_ids)

        self.assertEqual(result.content, "Content with artifacts")
        self.assertEqual(result.artifact_ids, artifact_ids)

    def test_intermediate_result_empty_content(self):
        """Should handle empty content string."""
        result = DeepResearchIntermediateResult(content="")
        self.assertEqual(result.content, "")

    def test_intermediate_result_serialization(self):
        """Should serialize and deserialize correctly."""
        original = DeepResearchIntermediateResult(
            content="Multi-line content\nwith special chars: !@#$%\n\nAnd more text", artifact_ids=["id1", "id2", "id3"]
        )

        serialized = original.model_dump()
        deserialized = DeepResearchIntermediateResult.model_validate(serialized)

        self.assertEqual(original.content, deserialized.content)
        self.assertEqual(original.artifact_ids, deserialized.artifact_ids)


class TestDeepResearchStates(BaseTest):
    """Test DeepResearchState and PartialDeepResearchState classes."""

    def test_shared_state_default_initialization(self):
        """Should initialize shared state with default values."""
        state = _SharedDeepResearchState()

        self.assertIsNone(state.todos)
        self.assertEqual(state.task_results, [])
        self.assertEqual(state.intermediate_results, [])
        self.assertIsNone(state.previous_response_id)
        self.assertIsNone(state.start_id)
        self.assertIsNone(state.graph_status)

    def test_deep_research_state_initialization(self):
        """Should initialize DeepResearchState with default messages."""
        state = DeepResearchState()

        self.assertEqual(state.messages, [])
        self.assertIsNone(state.todos)

    def test_partial_deep_research_state_initialization(self):
        """Should initialize PartialDeepResearchState with default messages."""
        state = PartialDeepResearchState()

        self.assertEqual(state.messages, [])
        # Should inherit all shared state defaults
        self.assertIsNone(state.todos)

    def test_state_with_all_fields_populated(self):
        """Should create state with all fields populated."""
        todos = [
            TodoItem(id="1", content="Task 1", status="pending", priority="high"),
            TodoItem(id="2", content="Task 2", status="completed", priority="medium"),
        ]

        task_results = [TaskResult(id="result-1", result="Analysis completed", status="completed")]

        intermediate_results = [DeepResearchIntermediateResult(content="Intermediate findings", artifact_ids=["art-1"])]

        messages = [HumanMessage(content="Test message"), AssistantMessage(content="Response")]

        test_notebook = DeepResearchNotebook(
            notebook_id="nb-456", notebook_type=DeepResearchType.PLANNING, title="Test Notebook"
        )
        state = DeepResearchState(
            todos=todos,
            task_results=task_results,
            intermediate_results=intermediate_results,
            messages=messages,
            previous_response_id="resp-123",
            conversation_notebooks=[test_notebook],
            current_run_notebooks=[test_notebook],
            start_id="start-789",
            graph_status="resumed",
        )

        self.assertEqual(len(cast(list[TodoItem], state.todos)), 2)
        self.assertEqual(len(state.task_results), 1)
        self.assertEqual(len(state.intermediate_results), 1)
        self.assertEqual(len(state.messages), 2)
        self.assertEqual(state.previous_response_id, "resp-123")
        self.assertEqual(len(state.conversation_notebooks), 1)
        self.assertEqual(state.conversation_notebooks[0].notebook_id, "nb-456")
        self.assertEqual(state.start_id, "start-789")
        self.assertEqual(state.graph_status, "resumed")

    @parameterized.expand(
        [
            ("", "empty string"),
            ("interrupted", "interrupted status"),
            ("resumed", "resumed status"),
        ]
    )
    def test_valid_graph_status_values(self, status, description):
        """Should accept valid graph status values."""
        state = DeepResearchState(graph_status=status)
        self.assertEqual(state.graph_status, status)

    def test_invalid_graph_status(self):
        """Should raise ValidationError for invalid graph status."""
        with self.assertRaises(ValidationError):
            DeepResearchState(graph_status="invalid_status")

    def test_state_reset_functionality(self):
        """Should reset state to defaults using get_reset_state method."""
        reset_state = DeepResearchState.get_reset_state()

        self.assertIsNone(reset_state.todos)
        self.assertEqual(reset_state.task_results, [])
        self.assertEqual(reset_state.messages, [])
        self.assertIsNone(reset_state.previous_response_id)

    def test_state_serialization_deserialization(self):
        """Should serialize and deserialize complex state correctly."""
        test_notebook = DeepResearchNotebook(
            notebook_id="nb-123", notebook_type=DeepResearchType.PLANNING, title="Test Notebook"
        )
        original_state = DeepResearchState(
            todos=[TodoItem(id="1", content="Test todo", status="pending", priority="high")],
            task_results=[TaskResult(id="task-1", result="Success", status="completed")],
            intermediate_results=[
                DeepResearchIntermediateResult(content="Test content", artifact_ids=["art-1", "art-2"])
            ],
            messages=[HumanMessage(content="Hello")],
            conversation_notebooks=[test_notebook],
            current_run_notebooks=[test_notebook],
        )

        serialized = original_state.model_dump()
        deserialized = DeepResearchState.model_validate(serialized)

        todos = cast(list[TodoItem], deserialized.todos)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].content, "Test todo")
        self.assertEqual(len(deserialized.task_results), 1)
        self.assertEqual(deserialized.task_results[0].id, "task-1")
        self.assertEqual(len(deserialized.intermediate_results), 1)
        self.assertEqual(deserialized.intermediate_results[0].content, "Test content")
        self.assertEqual(len(deserialized.messages), 1)
        self.assertEqual(len(deserialized.conversation_notebooks), 1)
        self.assertEqual(deserialized.conversation_notebooks[0].notebook_id, "nb-123")
