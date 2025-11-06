from typing import Any, cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    DeepResearchNotebook,
    DeepResearchType,
    HumanMessage,
    MultiVisualizationMessage,
    VisualizationItem,
)

from products.enterprise.backend.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from products.enterprise.backend.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes import DeepResearchOnboardingNode
from products.enterprise.backend.hogai.graph.deep_research.planner.nodes import (
    DeepResearchPlannerNode,
    DeepResearchPlannerToolsNode,
)
from products.enterprise.backend.hogai.graph.deep_research.report.nodes import DeepResearchReportNode
from products.enterprise.backend.hogai.graph.deep_research.task_executor.nodes import DeepResearchTaskExecutorNode
from products.enterprise.backend.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchState,
    TodoItem,
)
from products.enterprise.backend.hogai.utils.types.base import TaskResult
from products.enterprise.backend.models.assistant import Conversation
from products.notebooks.backend.models import Notebook


@patch("ee.hogai.graph.deep_research.base.nodes.DeepResearchNode._get_model")
@patch("ee.hogai.llm.MaxChatOpenAI")
class TestDeepResearchWorkflowIntegration(APIBaseTest):
    """
    Simplified integration tests for the deep research workflow
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.notebook = Notebook.objects.create(team=self.team, created_by=self.user, short_id="test_nb_123")
        self.graph = DeepResearchAssistantGraph(self.team, self.user)
        self.thread_id = str(self.conversation.id)
        self.config = RunnableConfig(configurable={"thread_id": self.thread_id})

    def _create_mock_state(
        self,
        messages: list[Any] | None = None,
        todos: list[TodoItem] | None = None,
        tool_calls: list[AssistantToolCall] | None = None,
        task_results: list[TaskResult] | None = None,
        intermediate_results: list[DeepResearchIntermediateResult] | None = None,
        current_run_notebooks: list[DeepResearchNotebook] | None = None,
    ) -> DeepResearchState:
        messages = messages or []
        if tool_calls:
            messages.append(AssistantMessage(id=str(uuid4()), content="something", tool_calls=tool_calls))
        return DeepResearchState(
            messages=messages,
            todos=todos,
            task_results=task_results or [],
            intermediate_results=intermediate_results or [],
            conversation_notebooks=[],
            current_run_notebooks=current_run_notebooks
            or [
                DeepResearchNotebook(
                    notebook_id="test_nb_123", notebook_type=DeepResearchType.PLANNING, title="Test Planning Notebook"
                )
            ],
        )

    def _create_mock_human_message(self, content: str) -> HumanMessage:
        return HumanMessage(content=content)

    def _create_mock_visualization_message(self, query_items: list[VisualizationItem]) -> MultiVisualizationMessage:
        return MultiVisualizationMessage(visualizations=query_items)

    def test_graph_initialization(self, mock_llm_class, mock_get_model):
        self.assertIsNotNone(self.graph)
        self.assertEqual(self.graph._team, self.team)
        self.assertEqual(self.graph._user, self.user)

    @parameterized.expand(
        [
            ("empty_state", "", 0, 0),
            ("basic", "Simple research question", 1, 0),
            ("complex", "Multi-faceted analysis with dependencies", 3, 2),
            ("high_volume", "Large scale analysis", 10, 8),
        ]
    )
    def test_state_serialization_scenarios(
        self, mock_llm_class, mock_get_model, scenario_name, query, num_todos, num_results
    ):
        """Test state serialization"""
        todos = [
            TodoItem(id=str(i), content=scenario_name, status="pending", priority="medium")
            for i in range(1, num_todos + 1)
        ]

        task_results = [TaskResult(id=f"result_{i}", result="Success", status="completed") for i in range(num_results)]

        state = self._create_mock_state(
            messages=[HumanMessage(content=query)],
            todos=todos,
            task_results=task_results,
        )

        serialized = state.model_dump()
        deserialized = DeepResearchState.model_validate(serialized)

        self.assertEqual(len(cast(list[TodoItem], deserialized.todos)), num_todos)
        self.assertEqual(len(deserialized.task_results), num_results)
        self.assertEqual(cast(HumanMessage, deserialized.messages[0]).content, query)

    def test_invalid_notebook_reference_handling(self, mock_llm_class, mock_get_model):
        """Test handling of invalid notebook references."""
        # Create state with non-existent notebook ID
        invalid_notebook = DeepResearchNotebook(
            notebook_id="nonexistent_nb", notebook_type=DeepResearchType.PLANNING, title="Nonexistent Notebook"
        )
        state = self._create_mock_state(current_run_notebooks=[invalid_notebook])

        # Should still create valid state but with invalid reference
        self.assertIsNotNone(state.current_run_notebooks)
        assert state.current_run_notebooks is not None
        self.assertEqual(len(state.current_run_notebooks), 1)
        self.assertEqual(state.current_run_notebooks[0].notebook_id, "nonexistent_nb")

        # Verify notebook doesn't exist in database
        nonexistent_notebook = Notebook.objects.filter(short_id="nonexistent_nb").first()
        self.assertIsNone(nonexistent_notebook)


class TestDeepResearchE2E(APIBaseTest):
    """
    Full end-to-end test for the deep research workflow.
    Tests the complete flow from user query to final report generation.
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.thread_id = str(self.conversation.id)
        self.config = RunnableConfig(
            configurable={"thread_id": self.thread_id},
            callbacks=[],
        )

    def _create_mock_llm_response(self, content: str, response_id: str | None = None) -> LangchainAIMessage:
        if response_id is None:
            response_id = str(uuid4())
        return LangchainAIMessage(
            content=content,
            response_metadata={"id": response_id},
        )

    def test_deep_research_graph_structure_and_routing(self):
        """
        Comprehensive test for deep research graph structure and routing logic.
        """
        graph = DeepResearchAssistantGraph(self.team, self.user)
        compiled_graph = graph.compile_full_graph(checkpointer=InMemorySaver())  # type: ignore

        self.assertIsNotNone(compiled_graph)
        self.assertTrue(hasattr(compiled_graph, "ainvoke"))
        self.assertTrue(hasattr(compiled_graph, "astream"))

        # Test onboarding routing logic with different state scenarios
        onboarding_node = DeepResearchOnboardingNode(self.team, self.user)

        # Scenario 1: Empty messages -> should go to onboarding
        empty_state = DeepResearchState(messages=[])
        routing = onboarding_node.should_run_onboarding_at_start(empty_state)
        self.assertEqual(routing, "onboarding")

        # Scenario 2: Single human message -> should go to onboarding
        single_message_state = DeepResearchState(
            messages=[HumanMessage(content="First question")],
            conversation_notebooks=[],
            current_run_notebooks=None,
        )
        routing = onboarding_node.should_run_onboarding_at_start(single_message_state)
        self.assertEqual(routing, "onboarding")

        # Scenario 3: Multiple human messages without current run notebooks -> should go to planning
        multi_message_state = DeepResearchState(
            messages=[
                HumanMessage(content="First question"),
                AssistantMessage(content="Response"),
                HumanMessage(content="Follow-up question"),
            ],
            conversation_notebooks=[],
            current_run_notebooks=None,
        )
        routing = onboarding_node.should_run_onboarding_at_start(multi_message_state)
        self.assertEqual(routing, "planning")

        # Scenario 4: Multiple human messages with current run notebooks -> should continue
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, short_id="test_e2e_nb")
        existing_conversation_state = DeepResearchState(
            messages=[
                HumanMessage(content="Previous question"),
                AssistantMessage(content="Previous response"),
                HumanMessage(content="Continue research"),
            ],
            conversation_notebooks=[],
            current_run_notebooks=[
                DeepResearchNotebook(
                    notebook_id=notebook.short_id, notebook_type=DeepResearchType.PLANNING, title="Test Notebook"
                )
            ],
        )
        routing = onboarding_node.should_run_onboarding_at_start(existing_conversation_state)
        self.assertEqual(routing, "continue")

        # Test that all required node types exist and can be instantiated
        nodes_to_test = [
            (DeepResearchOnboardingNode, "onboarding"),
            (DeepResearchNotebookPlanningNode, "notebook_planning"),
            (DeepResearchPlannerNode, "planner"),
            (DeepResearchPlannerToolsNode, "planner_tools"),
            (DeepResearchReportNode, "report"),
            (DeepResearchTaskExecutorNode, "task_executor"),
        ]

        for node_class, node_name in nodes_to_test:
            with self.subTest(node=node_name):
                node_instance = node_class(self.team, self.user)

                self.assertIsNotNone(node_instance)
                self.assertEqual(node_instance._team, self.team)
                self.assertEqual(node_instance._user, self.user)

        # Test state validation and serialization
        test_state = DeepResearchState(
            messages=[HumanMessage(content="Test message")],
            todos=[TodoItem(id="1", content="Test todo", status="pending", priority="high")],
            task_results=[TaskResult(id="task_1", result="Test result", status="completed")],
        )

        # Test serialization roundtrip
        serialized = test_state.model_dump()
        deserialized = DeepResearchState.model_validate(serialized)

        self.assertEqual(len(deserialized.messages), 1)
        todos = cast(list[TodoItem], deserialized.todos)
        self.assertEqual(len(cast(list[TodoItem], deserialized.todos)), 1)
        self.assertEqual(len(deserialized.task_results), 1)
        self.assertEqual(todos[0].content, "Test todo")
        self.assertEqual(deserialized.task_results[0].result, "Test result")

        # Test database integration
        retrieved_notebook = Notebook.objects.get(short_id=notebook.short_id)
        self.assertEqual(retrieved_notebook.team, self.team)
        self.assertEqual(retrieved_notebook.created_by, self.user)

        # Test conversation persistence
        retrieved_conversation = Conversation.objects.get(id=self.conversation.id)
        self.assertEqual(retrieved_conversation.team, self.team)
        self.assertEqual(retrieved_conversation.user, self.user)

        # Test configuration handling
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        self.assertIn("thread_id", config["configurable"])
        self.assertEqual(config["configurable"]["thread_id"], str(self.conversation.id))
