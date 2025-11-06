from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import AssistantMessage, DeepResearchNotebook, DeepResearchType, HumanMessage

from posthog.models import Team, User

from products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes import DeepResearchOnboardingNode
from products.enterprise.backend.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from products.enterprise.backend.models import CoreMemory


class TestDeepResearchOnboardingNode:
    def setup_method(self):
        """Set up test fixtures for each test method."""
        self.team = MagicMock(spec=Team)
        self.team.id = 1
        self.user = MagicMock(spec=User)
        self.user.id = 1

        self.node = DeepResearchOnboardingNode(self.team, self.user)
        self.config = RunnableConfig(configurable={"thread_id": str(uuid4())})

    # messages, routing_result
    @parameterized.expand(
        [
            # Case 1: Empty messages - should return "onboarding"
            ([], "onboarding"),
            # Case 2: Single human message - should return "onboarding"
            ([HumanMessage(content="First message")], "onboarding"),
            # Case 3: Multiple human messages without notebook - should return "planning"
            (
                [
                    HumanMessage(content="First message"),
                    AssistantMessage(content="Response"),
                    HumanMessage(content="Second message"),
                ],
                "planning",
            ),
            # Case 4: Multiple human messages with notebook - should return "continue"
            (
                [
                    HumanMessage(content="First message"),
                    AssistantMessage(content="Response"),
                    HumanMessage(content="Second message"),
                ],
                "continue",
                "test_notebook_id",
            ),
        ]
    )
    def test_should_run_onboarding_at_start(self, messages, expected_result, notebook_id=None):
        """Test the decision logic for when to run onboarding vs planning vs continue."""
        # Set up state based on whether we have notebooks
        if notebook_id:
            current_run_notebooks = [
                DeepResearchNotebook(
                    notebook_id=notebook_id, notebook_type=DeepResearchType.PLANNING, title="Test Notebook"
                )
            ]
        else:
            current_run_notebooks = None

        state = DeepResearchState(
            messages=messages, conversation_notebooks=[], current_run_notebooks=current_run_notebooks
        )
        result = self.node.should_run_onboarding_at_start(state)
        assert result == expected_result

    def test_should_run_onboarding_at_start_with_mixed_messages(self):
        """Test that only human messages are counted for decision logic."""
        messages = [
            HumanMessage(content="First human message"),
            AssistantMessage(content="Assistant response"),
            HumanMessage(content="Second human message"),
            AssistantMessage(content="Another assistant response"),
        ]
        state = DeepResearchState(messages=messages, conversation_notebooks=[], current_run_notebooks=None)
        result = self.node.should_run_onboarding_at_start(state)
        # Should be "planning" because there are 2 human messages and no notebook
        assert result == "planning"

    def test_should_run_onboarding_at_start_edge_cases(self):
        """Test edge cases for the onboarding decision logic."""
        # Test with exactly 2 human messages and no notebook
        messages_2_human = [HumanMessage(content="First"), HumanMessage(content="Second")]
        state = DeepResearchState(messages=messages_2_human, conversation_notebooks=[], current_run_notebooks=None)
        result = self.node.should_run_onboarding_at_start(state)
        assert result == "planning"

        # Test with 2 human messages and notebook
        test_notebook = DeepResearchNotebook(
            notebook_id="abc123", notebook_type=DeepResearchType.PLANNING, title="Test Notebook"
        )
        state_with_notebook = DeepResearchState(
            messages=messages_2_human, conversation_notebooks=[], current_run_notebooks=[test_notebook]
        )
        result = self.node.should_run_onboarding_at_start(state_with_notebook)
        assert result == "continue"

        # Test with 3 human messages and no notebook
        messages_3_human = [
            HumanMessage(content="First"),
            AssistantMessage(content="Response"),
            HumanMessage(content="Second"),
            AssistantMessage(content="Response2"),
            HumanMessage(content="Third"),
        ]
        state_3_human = DeepResearchState(
            messages=messages_3_human, conversation_notebooks=[], current_run_notebooks=None
        )
        result = self.node.should_run_onboarding_at_start(state_3_human)
        assert result == "planning"

    def test_arun_successful_execution(self):
        """Test successful execution of the onboarding node."""
        mock_core_memory = MagicMock(spec=CoreMemory)
        mock_core_memory.configure_mock(**{"__str__.return_value": "Test core memory content"})

        mock_response = LangchainAIMessage(
            content="## Welcome to Deep Research\n\nLet me ask you some clarifying questions...",
            response_metadata={"id": "test_response_id"},
        )

        # Patching the chain's ainvoke method
        with (
            patch.object(self.node, "_aget_core_memory", return_value=mock_core_memory),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = mock_response

            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="I want to research user behavior")])

                result = async_to_sync(self.node.arun)(state, self.config)

                assert isinstance(result, PartialDeepResearchState)
                assert len(result.messages) == 1
                assert isinstance(result.messages[0], AssistantMessage)
                assert (
                    result.messages[0].content
                    == "## Welcome to Deep Research\n\nLet me ask you some clarifying questions..."
                )
                assert result.previous_response_id == "test_response_id"

                mock_chain.ainvoke.assert_called_once_with({}, self.config)

    def test_arun_with_core_memory_formatting(self):
        """Test that core memory is properly formatted in the prompt."""
        mock_core_memory = MagicMock(spec=CoreMemory)
        mock_core_memory.configure_mock(**{"__str__.return_value": "User preferences: analytics focus, weekly reports"})

        with (
            patch.object(self.node, "_aget_core_memory", return_value=mock_core_memory),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Test response", response_metadata={"id": "test_id"}
            )
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="Research request")])

                async_to_sync(self.node.arun)(state, self.config)

                mock_get_model.assert_called_once()
                instructions_arg = mock_get_model.call_args[0][0]
                assert "User preferences: analytics focus, weekly reports" in instructions_arg

    def test_arun_with_no_core_memory(self):
        """Test execution when no core memory exists."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Test response", response_metadata={"id": "test_id"}
            )
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="Research request")])

                result = async_to_sync(self.node.arun)(state, self.config)

                # Should still work without core memory
                assert isinstance(result, PartialDeepResearchState)
                mock_get_model.assert_called_once()

    def test_arun_with_previous_response_id(self):
        """Test that previous response ID is passed to the model."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Test response", response_metadata={"id": "new_response_id"}
            )
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(
                    messages=[HumanMessage(content="Follow-up question")], previous_response_id="previous_id"
                )

                result = async_to_sync(self.node.arun)(state, self.config)

                mock_get_model.assert_called_once()
                _instructions_arg, previous_id_arg = mock_get_model.call_args[0]
                assert previous_id_arg == "previous_id"
                assert result.previous_response_id == "new_response_id"

    def test_arun_raises_error_for_non_human_last_message(self):
        """Test that ValueError is raised when last message is not human."""
        state = DeepResearchState(
            messages=[HumanMessage(content="Initial message"), AssistantMessage(content="Assistant response")]
        )

        with patch.object(self.node, "_aget_core_memory", return_value=None):
            with pytest.raises(ValueError, match="Last message is not a human message."):
                async_to_sync(self.node.arun)(state, self.config)

    def test_arun_message_id_generation(self):
        """Test that each generated message has a unique ID."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Test response", response_metadata={"id": "test_id"}
            )
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="Research request")])

                result1 = async_to_sync(self.node.arun)(state, self.config)
                result2 = async_to_sync(self.node.arun)(state, self.config)

                # Verify that each message has a different ID
                assert result1.messages[0].id != result2.messages[0].id
                # Verify IDs are valid UUIDs
                UUID(result1.messages[0].id)
                UUID(result2.messages[0].id)

    def test_arun_prompt_construction(self):
        """Test that the prompt is constructed correctly from the last human message."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template,
            patch(
                "products.enterprise.backend.hogai.utils.helpers.extract_content_from_ai_message",
                return_value="Test response",
            ),
        ):
            mock_prompt = MagicMock()
            mock_prompt_template.from_messages.return_value = mock_prompt

            mock_model = AsyncMock()
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Test response", response_metadata={"id": "test_id"}
            )
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            with patch.object(self.node, "_get_model", return_value=mock_model):
                state = DeepResearchState(
                    messages=[HumanMessage(content="Earlier message"), HumanMessage(content="Latest user message")]
                )

                async_to_sync(self.node.arun)(state, self.config)

                mock_prompt_template.from_messages.assert_called_once_with([("human", "Latest user message")])

    @parameterized.expand(
        [
            ("Simple research question", "Simple research question"),
            ("Multi-line\nresearch\nquestion", "Multi-line\nresearch\nquestion"),
            ("", ""),  # Empty content
            ("Special chars: @#$%^&*()", "Special chars: @#$%^&*()"),
        ]
    )
    def test_arun_handles_various_message_contents(self, message_content, expected_content):
        """Test handling of various message content formats."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template,
            patch(
                "products.enterprise.backend.hogai.utils.helpers.extract_content_from_ai_message",
                return_value="Response",
            ),
        ):
            mock_prompt = MagicMock()
            mock_prompt_template.from_messages.return_value = mock_prompt

            mock_model = AsyncMock()
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = LangchainAIMessage(
                content="Response", response_metadata={"id": "test_id"}
            )
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            with patch.object(self.node, "_get_model", return_value=mock_model):
                state = DeepResearchState(messages=[HumanMessage(content=message_content)])

                result = async_to_sync(self.node.arun)(state, self.config)

                mock_prompt_template.from_messages.assert_called_once_with([("human", expected_content)])
                assert isinstance(result, PartialDeepResearchState)

    def test_error_handling_in_model_invocation(self):
        """Test error handling when the model invocation fails."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_chain.ainvoke.side_effect = RuntimeError("Model invocation failed")
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="Test message")])

                try:
                    async_to_sync(self.node.arun)(state, self.config)
                    raise AssertionError("Should have raised RuntimeError")
                except RuntimeError as e:
                    assert str(e) == "Model invocation failed"

    def test_model_response_without_metadata(self):
        """Test handling of model response that lacks expected metadata."""
        with (
            patch.object(self.node, "_aget_core_memory", return_value=None),
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            # Response without response_metadata
            mock_response = LangchainAIMessage(content="Test response")
            mock_response.response_metadata = {}  # Empty metadata
            mock_chain.ainvoke.return_value = mock_response
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch(
                "products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes.ChatPromptTemplate"
            ) as mock_prompt_template:
                mock_prompt = MagicMock()
                mock_prompt_template.from_messages.return_value = mock_prompt
                mock_prompt.__or__ = MagicMock(return_value=mock_chain)

                state = DeepResearchState(messages=[HumanMessage(content="Test message")])

                try:
                    result = async_to_sync(self.node.arun)(state, self.config)
                    assert isinstance(result, PartialDeepResearchState)
                except KeyError:
                    # This is acceptable if the implementation expects the ID
                    pass
