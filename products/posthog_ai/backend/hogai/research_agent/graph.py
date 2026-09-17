from typing import Literal

from products.posthog_ai.backend.hogai.core.loop_graph.graph import AgentLoopGraph
from products.posthog_ai.backend.hogai.core.title_generator.nodes import TitleGeneratorNode
from products.posthog_ai.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.posthog_ai.backend.hogai.research_agent.mode_manager import ResearchAgentModeManager
from products.posthog_ai.backend.hogai.utils.types.base import AssistantGraphName, AssistantNodeName


class ResearchAgentGraph(AgentLoopGraph):
    @property
    def mode_manager_class(self) -> type[ResearchAgentModeManager]:
        return ResearchAgentModeManager

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.DEEP_RESEARCH

    def add_title_generator(self, end_node: AssistantNodeName = AssistantNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self._graph.add_node(AssistantNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        return (
            self.add_agent_node(is_start_node=True)
            .add_agent_tools_node()
            .add_title_generator()
            .compile(checkpointer=checkpointer)
        )
