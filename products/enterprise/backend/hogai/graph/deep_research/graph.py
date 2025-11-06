from typing import Literal, Optional

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.hogai.graph.base import BaseAssistantGraph
from products.enterprise.backend.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from products.enterprise.backend.hogai.graph.deep_research.onboarding.nodes import DeepResearchOnboardingNode
from products.enterprise.backend.hogai.graph.deep_research.planner.nodes import (
    DeepResearchPlannerNode,
    DeepResearchPlannerToolsNode,
)
from products.enterprise.backend.hogai.graph.deep_research.report.nodes import DeepResearchReportNode
from products.enterprise.backend.hogai.graph.deep_research.task_executor.nodes import DeepResearchTaskExecutorNode
from products.enterprise.backend.hogai.graph.deep_research.types import (
    DeepResearchNodeName,
    DeepResearchState,
    PartialDeepResearchState,
)
from products.enterprise.backend.hogai.graph.title_generator.nodes import TitleGeneratorNode
from products.enterprise.backend.hogai.utils.types.base import AssistantGraphName


class DeepResearchAssistantGraph(BaseAssistantGraph[DeepResearchState, PartialDeepResearchState]):
    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.DEEP_RESEARCH

    @property
    def state_type(self) -> type[DeepResearchState]:
        return DeepResearchState

    def add_onboarding_node(
        self, node_map: Optional[dict[Literal["onboarding", "planning", "continue"], DeepResearchNodeName]] = None
    ):
        builder = self._graph
        self._has_start_node = True
        deep_research_onboarding = DeepResearchOnboardingNode(self._team, self._user)
        builder.add_node(DeepResearchNodeName.ONBOARDING, deep_research_onboarding)
        builder.add_conditional_edges(
            DeepResearchNodeName.START,
            deep_research_onboarding.should_run_onboarding_at_start,
            node_map  # type: ignore
            or {
                "onboarding": DeepResearchNodeName.ONBOARDING,
                "planning": DeepResearchNodeName.NOTEBOOK_PLANNING,
                "continue": DeepResearchNodeName.PLANNER,
            },
        )
        return self

    def add_notebook_nodes(self, next_node: DeepResearchNodeName = DeepResearchNodeName.PLANNER):
        builder = self._graph

        deep_research_notebook_planning = DeepResearchNotebookPlanningNode(self._team, self._user)
        builder.add_node(DeepResearchNodeName.NOTEBOOK_PLANNING, deep_research_notebook_planning)
        builder.add_edge(DeepResearchNodeName.NOTEBOOK_PLANNING, next_node)

        return self

    def add_planner_nodes(self, next_node: DeepResearchNodeName = DeepResearchNodeName.REPORT):
        builder = self._graph
        deep_research_planner = DeepResearchPlannerNode(self._team, self._user)
        deep_research_planner_tools = DeepResearchPlannerToolsNode(self._team, self._user)
        builder.add_node(DeepResearchNodeName.PLANNER, deep_research_planner)
        builder.add_node(DeepResearchNodeName.PLANNER_TOOLS, deep_research_planner_tools)
        builder.add_edge(DeepResearchNodeName.PLANNER, DeepResearchNodeName.PLANNER_TOOLS)
        builder.add_conditional_edges(
            DeepResearchNodeName.PLANNER_TOOLS,
            deep_research_planner_tools.router,
            path_map={
                "task_executor": DeepResearchNodeName.TASK_EXECUTOR,
                "continue": DeepResearchNodeName.PLANNER,
                "end": next_node,
            },
        )

        return self

    def add_task_executor(self, next_node: DeepResearchNodeName = DeepResearchNodeName.PLANNER):
        """
        Add the core task executor node that handles task execution.
        """
        executor_node = DeepResearchTaskExecutorNode(self._team, self._user)
        self.add_node(DeepResearchNodeName.TASK_EXECUTOR, executor_node)
        self.add_edge(DeepResearchNodeName.TASK_EXECUTOR, next_node)
        return self

    def add_report_node(self, next_node: DeepResearchNodeName = DeepResearchNodeName.END):
        builder = self._graph
        deep_research_report = DeepResearchReportNode(self._team, self._user)
        builder.add_node(DeepResearchNodeName.REPORT, deep_research_report)
        builder.add_edge(DeepResearchNodeName.REPORT, next_node)
        return self

    def add_title_generator(self, end_node: DeepResearchNodeName = DeepResearchNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user)
        self._graph.add_node(DeepResearchNodeName.TITLE_GENERATOR, title_generator)
        self._graph.add_edge(DeepResearchNodeName.START, DeepResearchNodeName.TITLE_GENERATOR)
        self._graph.add_edge(DeepResearchNodeName.TITLE_GENERATOR, end_node)
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return (
            self.add_onboarding_node()
            .add_notebook_nodes()
            .add_planner_nodes()
            .add_report_node()
            .add_task_executor()
            .compile(checkpointer=checkpointer)
        )
