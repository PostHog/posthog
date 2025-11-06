from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage as LangchainAIMessage

from posthog.schema import HumanMessage

from products.enterprise.backend.hogai.graph.title_generator.nodes import TitleGeneratorNode
from products.enterprise.backend.hogai.utils.tests import FakeChatOpenAI
from products.enterprise.backend.hogai.utils.types import AssistantState
from products.enterprise.backend.models.assistant import Conversation


class TestTitleGenerator(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    def test_saves_a_title(self):
        """Test that a title is generated and saved for a conversation without a title."""
        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Test Title")]),
        ):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Test Message")]),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Test Title")

    def test_saves_a_long_title_truncated(self):
        """Test that if a title over our length is generated, it is truncated on save, without error."""
        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content=("Long " * 100).strip())]),
        ):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Test Message")]),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(
                self.conversation.title,
                "Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long Long",
            )

    def test_title_already_set_should_stay_the_same(self):
        """Test that existing conversation titles are not overwritten."""
        self.conversation.title = "Existing Title"
        self.conversation.save()

        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="New Title")]),
        ):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Test Message")]),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Existing Title")

    def test_two_messages_in_conversation_no_title_should_set_title(self):
        """Test that a title is generated when there are multiple messages in the conversation."""
        mock_model = FakeChatOpenAI(responses=[LangchainAIMessage(content="Conversation Title")])

        with patch.object(TitleGeneratorNode, "_model", new=Mock(return_value=mock_model)):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="First message"),
                        HumanMessage(content="Second message"),
                    ]
                ),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Conversation Title")

    def test_no_messages_should_skip(self):
        """Test that title generation is skipped when there are no messages in the conversation."""
        node = TitleGeneratorNode(self.team, self.user)
        new_state = node.run(
            AssistantState(messages=[]),
            {"configurable": {"thread_id": self.conversation.id}},
        )
        self.assertIsNone(new_state)
        # Refresh from DB to ensure we get latest value
        self.conversation.refresh_from_db()
        self.assertIsNone(self.conversation.title)

    def test_handles_json_content_without_error(self):
        """Test that title generation works when user message contains JSON with curly braces."""
        json_content = """Hi Max,

The query below is currently set up as an SQL insight, but the visualization options for SQL insights are quite limited. Could you help convert this into a Trends Insight instead?

```sql
{
  "kind": "DataVisualizationNode",
  "source": {
    "kind": "HogQLQuery",
    "query": "WITH eligible_users AS (SELECT DISTINCT distinct_id FROM events WHERE event = 'CompleteRegistration' AND timestamp < now() - INTERVAL 7 DAY) SELECT e.event, count(e.uuid) AS event_count FROM events e CROSS JOIN eligible_users eu WHERE e.distinct_id = eu.distinct_id AND e.timestamp >= now() - INTERVAL 30 DAY AND e.timestamp < now() GROUP BY e.event ORDER BY event_count DESC"
  },
  "tableSettings": {
    "conditionalFormatting": []
  },
  "chartSettings": {}
}
```"""

        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Convert SQL to Trends")]),
        ):
            node = TitleGeneratorNode(self.team, self.user)

            # This should not raise a KeyError about missing template variables
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content=json_content)]),
                {"configurable": {"thread_id": self.conversation.id}},
            )

            self.assertIsNone(new_state)
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Convert SQL to Trends")
