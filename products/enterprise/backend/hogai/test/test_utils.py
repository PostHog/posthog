from posthog.test.base import BaseTest

from posthog.schema import AssistantMessage, AssistantTrendsQuery, FailureMessage, HumanMessage, VisualizationMessage

from products.enterprise.backend.hogai.utils.helpers import filter_and_merge_messages
from products.enterprise.backend.hogai.utils.types.base import AssistantMessageUnion


class TestTrendsUtils(BaseTest):
    def test_filters_and_merges_human_messages(self):
        conversation: list[AssistantMessageUnion] = [
            HumanMessage(content="Text"),
            FailureMessage(content="Error"),
            HumanMessage(content="Text"),
            VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan"),
            HumanMessage(content="Text2"),
        ]
        messages = filter_and_merge_messages(conversation)
        self.assertEqual(
            [
                HumanMessage(content="Text\nText"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan"),
                HumanMessage(content="Text2"),
            ],
            messages,
        )

    def test_filters_typical_conversation(self):
        messages = filter_and_merge_messages(
            [
                HumanMessage(content="Question 1"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                AssistantMessage(content="Summary 2"),
            ]
        )
        self.assertEqual(len(messages), 6)
        self.assertEqual(
            messages,
            [
                HumanMessage(content="Question 1"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                AssistantMessage(content="Summary 2"),
            ],
        )

    def test_joins_human_messages(self):
        messages = filter_and_merge_messages(
            [
                HumanMessage(content="Question 1"),
                HumanMessage(content="Question 2"),
            ]
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages,
            [
                HumanMessage(content="Question 1\nQuestion 2"),
            ],
        )
