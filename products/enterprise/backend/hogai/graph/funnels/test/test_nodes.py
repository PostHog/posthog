from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from posthog.schema import AssistantFunnelsFilter, AssistantFunnelsQuery, HumanMessage, VisualizationMessage

from products.enterprise.backend.hogai.graph.funnels.nodes import FunnelGeneratorNode, FunnelsSchemaGeneratorOutput
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState


class TestFunnelsGeneratorNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantFunnelsQuery(series=[])

    async def test_node_runs(self):
        node = FunnelGeneratorNode(self.team, self.user)
        with patch.object(FunnelGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: FunnelsSchemaGeneratorOutput(query=self.schema).model_dump()
            )
            new_state = await node.arun(
                AssistantState(messages=[HumanMessage(content="Text")], plan="Plan", root_tool_insight_plan="question"),
                {},
            )
            self.assertEqual(
                new_state,
                PartialAssistantState(
                    messages=[
                        VisualizationMessage(
                            query="question", answer=self.schema, plan="Plan", id=new_state.messages[0].id
                        )
                    ],
                    intermediate_steps=None,
                    plan=None,
                    rag_context=None,
                ),
            )

    def test_schema_does_not_require_aggregation_by_hogql(self):
        """Catches the regression where the schema set funnelAggregateByHogQL."""
        schema = AssistantFunnelsQuery(series=[], funnelsFilter=AssistantFunnelsFilter())
        self.assertIsNone(schema.funnelsFilter.funnelAggregateByHogQL)
