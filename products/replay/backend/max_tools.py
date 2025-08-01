import logging
from pydantic import BaseModel, Field
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.tools import create_final_answer_model
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState, PartialTaxonomyAgentState
from ee.hogai.tool import MaxTool
from posthog.schema import MaxRecordingUniversalFilters
from .prompts import USER_FILTER_OPTIONS_PROMPT

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class SessionReplayFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team):
        super().__init__(team=team)

    def get_tools(self) -> list:
        """Get all available tools for filter options."""
        final_answer = create_final_answer_model(MaxRecordingUniversalFilters)

        return [*self._get_default_tools(), final_answer]

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._generate_properties_yaml(props)


class SessionReplayFilterNode(
    TaxonomyAgentNode[TaxonomyAgentState, PartialTaxonomyAgentState[MaxRecordingUniversalFilters]]
):
    """Node for generating filtering options for session replay."""

    def __init__(self, team, user, toolkit_class: SessionReplayFilterOptionsToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def get_system_prompts(self) -> list[str]:
        """Get default system prompts. Override in subclasses for custom prompts."""
        from .prompts import (
            PRODUCT_DESCRIPTION_PROMPT,
            SESSION_REPLAY_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT,
            DATE_FIELDS_PROMPT,
        )

        return [
            PRODUCT_DESCRIPTION_PROMPT,
            SESSION_REPLAY_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT,
            DATE_FIELDS_PROMPT,
            *super()._get_default_system_prompts(),
        ]


class SessionReplayFilterOptionsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, PartialTaxonomyAgentState[MaxRecordingUniversalFilters]]
):
    """Node for generating filtering options for session replay."""

    def __init__(self, team, user, toolkit_class: SessionReplayFilterOptionsToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)


class SessionReplayFilterOptionsGraph(
    TaxonomyAgent[TaxonomyAgentState, PartialTaxonomyAgentState[MaxRecordingUniversalFilters]]
):
    """Graph for generating filtering options for session replay."""

    def __init__(self, team, user):
        super().__init__(
            team,
            user,
            loop_node_class=SessionReplayFilterNode,
            tools_node_class=SessionReplayFilterOptionsToolsNode,
            toolkit_class=SessionReplayFilterOptionsToolkit,
        )


class SearchSessionRecordingsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to recordings filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class SearchSessionRecordingsTool(MaxTool):
    name: str = "search_session_recordings"
    description: str = (
        "Update session recordings filters on this page, in order to search for session recordings by any criteria."
    )
    thinking_message: str = "Coming up with session recordings filters"
    root_system_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    async def _arun_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        # Create the graph
        graph = SessionReplayFilterOptionsGraph(team=self._team, user=self._user)
        instructions = USER_FILTER_OPTIONS_PROMPT.format(
            change=change, current_filters=self.context.get("current_filters", {})
        )
        # Set the context
        graph_context = {
            "instructions": instructions,
            "output": None,
            "messages": [],
            "tool_progress_messages": [],
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context)

        if "output" not in result or result["output"] is None:
            last_message = result["intermediate_steps"][-1]
            help_content = "I need more information to proceed."

            tool_call_id = getattr(last_message, "tool", None)

            if tool_call_id == "ask_user_for_help" or tool_call_id == "max_iterations":
                content = getattr(last_message, "tool_input", None)
                help_content = str(content)

            current_filters = MaxRecordingUniversalFilters.model_validate(self.context.get("current_filters", {}))

            return help_content, current_filters

        try:
            result = MaxRecordingUniversalFilters.model_validate(result["output"])
        except Exception as e:
            raise ValueError(f"Failed to generate MaxRecordingUniversalFilters: {e}")

        return "✅ Updated session recordings filters.", result
