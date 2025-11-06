from posthog.test.base import BaseTest

from langgraph.checkpoint.memory import InMemorySaver

from products.enterprise.backend.hogai.graph.base import AssistantNode
from products.enterprise.backend.hogai.graph.base.graph import BaseAssistantGraph
from products.enterprise.backend.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import AssistantGraphName
from products.enterprise.backend.models import Conversation


class TestAssistantGraph(BaseTest):
    async def test_pydantic_state_resets_with_none(self):
        """When a None field is set, it should be reset to None."""

        class TestAssistantGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

        graph = TestAssistantGraph(self.team, self.user)

        class TestNode(AssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config):
                return PartialAssistantState(start_id=None)

        compiled_graph = (
            graph.add_node(AssistantNodeName.ROOT, TestNode(self.team, self.user))
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile(checkpointer=InMemorySaver())
        )
        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        state = await compiled_graph.ainvoke(
            AssistantState(messages=[], graph_status="resumed", start_id=None),
            {"configurable": {"thread_id": conversation.id}},
        )
        self.assertEqual(state["start_id"], None)
        self.assertEqual(state["graph_status"], "resumed")
