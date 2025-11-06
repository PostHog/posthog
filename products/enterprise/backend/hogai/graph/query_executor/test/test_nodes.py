from typing import cast

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    FunnelVizType,
    HumanMessage,
    QueryStatus,
    VisualizationMessage,
)

from posthog.api.services.query import process_query_dict

from products.enterprise.backend.hogai.graph.query_executor.nodes import QueryExecutorNode
from products.enterprise.backend.hogai.graph.query_executor.prompts import (
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
)
from products.enterprise.backend.hogai.utils.types import AssistantState
from products.enterprise.backend.hogai.utils.types.base import PartialAssistantState


class TestQueryExecutorNode(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False
    maxDiff = None

    @patch(
        "products.enterprise.backend.hogai.graph.query_executor.query_executor.process_query_dict",
        side_effect=process_query_dict,
    )
    async def test_node_runs(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    AssistantMessage(
                        content="Text",
                        id="test2",
                        tool_calls=[
                            AssistantToolCall(
                                id="tool1",
                                name="create_and_query_insight",
                                args={"query_kind": "trends", "query_description": "test query"},
                            )
                        ],
                    ),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        id="test3",
                        initiator="test",
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = cast(AssistantToolCallMessage, new_state.messages[0])
        self.assertIn(
            "Here is the results table of the TrendsQuery I created to answer your latest question:", msg.content
        )
        self.assertEqual(msg.type, "tool")
        self.assertEqual(msg.tool_call_id, "tool1")
        self.assertIsNotNone(msg.id)
        self.assertFalse(new_state.root_tool_call_id)
        self.assertFalse(new_state.root_tool_insight_plan)
        self.assertFalse(new_state.root_tool_insight_type)

    @patch(
        "ee.hogai.graph.query_executor.query_executor.process_query_dict",
        side_effect=ValueError("You have not glibbled the glorp before running this."),
    )
    async def test_node_handles_internal_error(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        id="test2",
                        initiator="test",
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = cast(AssistantMessage, new_state.messages[0])
        self.assertEqual(msg.content, "There was an unknown error running this query.")
        self.assertEqual(msg.type, "ai/failure")
        self.assertIsNotNone(msg.id)

    @patch(
        "ee.hogai.graph.query_executor.query_executor.process_query_dict",
        side_effect=ValidationError(
            "This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam."
        ),
    )
    async def test_node_handles_exposed_error(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        id="test2",
                        initiator="test",
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = new_state.messages[0]
        self.assertEqual(
            cast(AssistantMessage, msg).content,
            "There was an error running this query: This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam.",
        )
        self.assertEqual(msg.type, "ai/failure")
        self.assertIsNotNone(msg.id)

    async def test_node_requires_a_viz_message_in_state(self):
        node = QueryExecutorNode(self.team, self.user)

        with self.assertRaisesMessage(
            ValueError, "Expected a visualization message, found <class 'posthog.schema.HumanMessage'>"
        ):
            await node.arun(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text"),
                    ],
                    plan="Plan",
                    start_id="test",
                    root_tool_call_id="tool1",
                    root_tool_insight_plan="test query",
                    root_tool_insight_type="trends",
                ),
                {},
            )

    async def test_fallback_to_json(self):
        node = QueryExecutorNode(self.team, self.user)
        with patch(
            "products.enterprise.backend.hogai.graph.query_executor.query_executor.process_query_dict"
        ) as mock_process_query_dict:
            mock_process_query_dict.return_value = QueryStatus(
                id="test", team_id=self.team.pk, query_async=True, complete=True, results=[{"test": "test"}]
            )

            new_state = await node.arun(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            id="test2",
                            initiator="test",
                        ),
                    ],
                    plan="Plan",
                    start_id="test",
                    root_tool_call_id="tool1",
                    root_tool_insight_plan="test query",
                    root_tool_insight_type="trends",
                ),
                {},
            )
            new_state = cast(PartialAssistantState, new_state)
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = cast(AssistantMessage, new_state.messages[0])
            self.assertIn(
                "Here is the results table of the TrendsQuery I created to answer your latest question:", msg.content
            )
            self.assertEqual(msg.type, "tool")
            self.assertIsNotNone(msg.id)

    def test_get_example_prompt(self):
        node = QueryExecutorNode(self.team, self.user)

        # Test Trends Query
        trends_message = VisualizationMessage(
            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
            plan="Plan",
            id="test",
            initiator="test",
        )
        self.assertEqual(node._get_example_prompt(trends_message), TRENDS_EXAMPLE_PROMPT)

        # Test Funnel Query - Steps (default)
        funnel_steps_message = VisualizationMessage(
            answer=AssistantFunnelsQuery(series=[]),
            plan="Plan",
            id="test",
            initiator="test",
        )
        self.assertEqual(node._get_example_prompt(funnel_steps_message), FUNNEL_STEPS_EXAMPLE_PROMPT)

        # Test Funnel Query - Time to Convert
        funnel_time_message = VisualizationMessage(
            answer=AssistantFunnelsQuery(
                series=[],
                funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
            ),
            plan="Plan",
            id="test",
            initiator="test",
        )
        self.assertEqual(node._get_example_prompt(funnel_time_message), FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT)

        # Test Funnel Query - Trends
        funnel_trends_message = VisualizationMessage(
            answer=AssistantFunnelsQuery(
                series=[],
                funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
            ),
            plan="Plan",
            id="test",
            initiator="test",
        )
        self.assertEqual(node._get_example_prompt(funnel_trends_message), FUNNEL_TRENDS_EXAMPLE_PROMPT)

        # Test Retention Query
        retention_message = VisualizationMessage(
            answer=AssistantRetentionQuery(
                retentionFilter=AssistantRetentionFilter(
                    targetEntity=AssistantRetentionEventsNode(name="event"),
                    returningEntity=AssistantRetentionEventsNode(name="event"),
                )
            ),
            plan="Plan",
            id="test",
            initiator="test",
        )
        self.assertEqual(node._get_example_prompt(retention_message), RETENTION_EXAMPLE_PROMPT)
