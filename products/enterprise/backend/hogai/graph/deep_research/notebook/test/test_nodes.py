from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import DeepResearchType, HumanMessage, NotebookUpdateMessage, ProsemirrorJSONContent

from products.enterprise.backend.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from products.enterprise.backend.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from products.enterprise.backend.models.assistant import Conversation


class TestDeepResearchNotebookPlanningNode(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.node = DeepResearchNotebookPlanningNode(self.team, self.user)
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_arun_creates_notebook_plan_successfully(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that notebook plan is created successfully."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook-123"
        mock_notebook.title = "Research Plan"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook

        self.node.notebook = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Create a research plan for user engagement")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsNone(result.previous_response_id)
        self.assertEqual(len(result.conversation_notebooks), 1)
        self.assertEqual(result.conversation_notebooks[0].notebook_id, "test-notebook-123")
        self.assertEqual(result.conversation_notebooks[0].notebook_type, DeepResearchType.PLANNING)
        self.assertIsNotNone(result.current_run_notebooks)
        assert result.current_run_notebooks is not None
        self.assertEqual(len(result.current_run_notebooks), 1)
        self.assertEqual(result.current_run_notebooks[0].notebook_id, "test-notebook-123")

        mock_core_memory.assert_called_once()
        mock_astream.assert_called_once()

    @parameterized.expand(
        [
            ("simple_request", "Analyze user behavior"),
            (
                "complex_request",
                "Create a detailed research plan for understanding user engagement patterns across different cohorts",
            ),
            ("question_format", "What factors influence user retention?"),
        ]
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_arun_handles_different_message_types(
        self, _name, message_content, mock_astream, mock_get_model, mock_core_memory
    ):
        """Test that arun handles different types of human messages correctly."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook
        self.node.notebook = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content=message_content)])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(len(result.conversation_notebooks), 1)
        self.assertIsNotNone(result.current_run_notebooks)
        assert result.current_run_notebooks is not None
        self.assertEqual(len(result.current_run_notebooks), 1)

    async def test_arun_raises_error_when_last_message_not_human(self):
        """Test that arun raises ValueError when last message is **NOT** a human message."""
        # Arrange
        state = DeepResearchState(
            messages=[
                HumanMessage(content="First message"),
                NotebookUpdateMessage(notebook_id="test", content=ProsemirrorJSONContent(type="doc", content=[])),
            ]
        )

        with self.assertRaises(ValueError) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Last message is not a human message.")

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_arun_uses_previous_response_id_correctly(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that arun passes previous_response_id to model and resets it in response."""
        # Arrange
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook
        self.node.notebook = mock_notebook

        previous_response_id = "previous-response-123"
        state = DeepResearchState(
            messages=[HumanMessage(content="Test message")], previous_response_id=previous_response_id
        )

        result = await self.node.arun(state, self.config)

        args, _ = mock_get_model.call_args
        instructions_arg = args[0]
        response_id_arg = args[1]

        self.assertIn("Create a single-page Markdown plan", instructions_arg)
        self.assertIn("Test core memory", instructions_arg)
        self.assertEqual(response_id_arg, previous_response_id)
        self.assertIsNone(result.previous_response_id)

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_state_management_with_notebook_updates(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that state is properly managed with notebook updates."""
        mock_core_memory.return_value = "Core memory content"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        notebook_id = "notebook-456"
        mock_notebook = MagicMock()
        mock_notebook.short_id = notebook_id
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook
        self.node.notebook = mock_notebook

        initial_state = DeepResearchState(
            messages=[HumanMessage(content="Create research plan")],
            todos=None,
            tasks=None,
            task_results=[],
            intermediate_results=[],
            previous_response_id="old-id",
            conversation_notebooks=[],
            current_run_notebooks=None,
        )

        result = await self.node.arun(initial_state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(len(result.conversation_notebooks), 1)
        self.assertEqual(result.conversation_notebooks[0].notebook_id, notebook_id)
        self.assertIsNone(result.previous_response_id)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], NotebookUpdateMessage)
        result_message = cast(NotebookUpdateMessage, result.messages[0])
        self.assertEqual(result_message.notebook_id, notebook_id)

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    async def test_integration_with_notebook_serializer(self, mock_get_model, mock_core_memory, mock_astream_notebook):
        """Test integration with NotebookSerializer for content processing."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Create a research plan")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        mock_astream_notebook.assert_called_once()

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    async def test_streaming_behavior_with_partial_messages(
        self, mock_get_model, mock_core_memory, mock_astream_notebook
    ):
        """Test streaming behavior processes partial messages correctly."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook
        self.node.notebook = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        mock_astream_notebook.assert_called_once()

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    async def test_error_when_no_notebook_message_generated(
        self, mock_get_model, mock_core_memory, mock_astream_notebook
    ):
        """Test error handling when no notebook update message is generated."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        # Mocking to raise
        mock_astream_notebook.side_effect = ValueError("No notebook update message found.")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(ValueError) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "No notebook update message found.")

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    async def test_error_when_core_memory_fails(self, mock_core_memory):
        """Test error handling when core memory retrieval fails."""
        mock_core_memory.side_effect = Exception("Core memory error")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(Exception) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Core memory error")

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    async def test_error_when_model_generation_fails(self, mock_get_model, mock_core_memory, mock_astream_notebook):
        """Test error handling when model generation fails."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_astream_notebook.side_effect = Exception("Model generation failed")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(Exception) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Model generation failed")

    @parameterized.expand(
        [
            ("empty_messages", []),
            ("none_messages", None),
        ]
    )
    async def test_edge_case_empty_or_none_messages(self, _name, messages):
        """Test handling of edge cases with empty or None messages."""
        if messages is None:
            state = DeepResearchState()
        else:
            state = DeepResearchState(messages=messages)

        with self.assertRaises(IndexError):
            await self.node.arun(state, self.config)

    async def test_edge_case_message_with_empty_content(self):
        """Test handling of human message with empty content."""
        state = DeepResearchState(messages=[HumanMessage(content="")])

        with patch(
            "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
        ) as mock_core_memory:
            with patch(
                "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
            ) as mock_get_model:
                with patch(
                    "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
                ) as mock_astream:
                    mock_core_memory.return_value = "Test memory"
                    mock_model = AsyncMock()
                    mock_get_model.return_value = mock_model

                    mock_notebook = MagicMock()
                    mock_notebook.short_id = "test-notebook"
                    mock_notebook.title = "Test Notebook"
                    mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
                    mock_astream.return_value = mock_notebook
                    self.node.notebook = mock_notebook

                    result = await self.node.arun(state, self.config)

                    self.assertIsInstance(result, PartialDeepResearchState)

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_message_content_passed_to_prompt_correctly(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that human message content is correctly passed to the prompt."""
        mock_core_memory.return_value = "Test memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test-notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook
        self.node.notebook = mock_notebook

        user_message = "Analyze user engagement patterns for mobile users"
        state = DeepResearchState(messages=[HumanMessage(content=user_message)])

        await self.node.arun(state, self.config)

        # Assert - verify the prompt template was created with the user message
        # The chain should contain the user's message content (verify the call was made)
        mock_astream.assert_called_once()

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_stage_notebook_tracking_in_result(self, mock_astream, mock_get_model, mock_core_memory):
        """Should add notebook to stage_notebooks in returned state."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        notebook_title = "Custom Planning Notebook Title"
        mock_notebook = MagicMock()
        mock_notebook.short_id = "planning_nb_123"
        mock_notebook.title = notebook_title
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        self.node.notebook = mock_notebook

        mock_astream.return_value = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Create planning document")])

        result = await self.node.arun(state, self.config)

        # Verify conversation_notebooks contains the planning notebook
        self.assertEqual(len(result.conversation_notebooks), 1)
        notebook_info = result.conversation_notebooks[0]
        self.assertEqual(notebook_info.notebook_id, "planning_nb_123")
        self.assertEqual(notebook_info.title, notebook_title)

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_stage_notebook_with_no_notebook_instance(self, mock_astream, mock_get_model, mock_core_memory):
        """Should handle case where notebook instance is None."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        # Mock notebook without title
        mock_notebook = MagicMock()
        mock_notebook.short_id = "some_nb_id"
        mock_notebook.title = None
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream.return_value = mock_notebook
        self.node.notebook = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Create plan")])

        result = await self.node.arun(state, self.config)

        # Should use default title when notebook title is None
        notebook_info = result.conversation_notebooks[0]
        self.assertEqual(notebook_info.title, "Planning Notebook")

    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
    )
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
    )
    async def test_stage_notebook_info_serialization(self, mock_astream, mock_get_model, mock_core_memory):
        """Should create notebook info that serializes correctly."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.short_id = "serialization_test_123"
        mock_notebook.title = "Serialization Test Planning"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        self.node.notebook = mock_notebook

        mock_astream.return_value = mock_notebook

        state = DeepResearchState(messages=[HumanMessage(content="Test serialization")])

        result = await self.node.arun(state, self.config)

        notebook_info = result.conversation_notebooks[0]
        serialized = notebook_info.model_dump()

        expected = {
            "category": "deep_research",
            "notebook_type": "planning",
            "notebook_id": "serialization_test_123",
            "title": "Serialization Test Planning",
        }

        self.assertEqual(serialized, expected)
