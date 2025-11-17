import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import MaxRecordingUniversalFilters

from posthog.models import Team, User

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool

from .prompts import (
    DATE_FIELDS_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class SessionReplayFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    def _get_custom_tools(self) -> list:
        """Get custom tools for filter options."""

        class final_answer(base_final_answer[MaxRecordingUniversalFilters]):
            __doc__ = base_final_answer.__doc__

        return [final_answer]

    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._format_properties_yaml(props)


class SessionReplayFilterNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[MaxRecordingUniversalFilters]]):
    """Node for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SessionReplayFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get default system prompts. Override in subclasses for custom prompts."""
        all_messages = [
            PRODUCT_DESCRIPTION_PROMPT,
            SESSION_REPLAY_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT,
            DATE_FIELDS_PROMPT,
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")


class SessionReplayFilterOptionsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[MaxRecordingUniversalFilters]]
):
    """Node for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SessionReplayFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)


class SessionReplayFilterOptionsGraph(
    TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[MaxRecordingUniversalFilters]]
):
    """Graph for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User):
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
    description: str = """
    - Update session recordings filters on this page, in order to search for session recordings.
    - When to use the tool:
      * When the user asks to update session recordings filters
        - "update" synonyms: "change", "modify", "adjust", and similar
        - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
      * When the user asks to search for session recordings
        - "search for" synonyms: "find", "look up", and similar
    - When NOT to use the tool:
      * When the user asks to summarize session recordings
    """
    context_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    async def _invoke_graph(self, change: str) -> dict[str, Any] | Any:
        """
        Reusable method to call graph to avoid code/prompt duplication and enable
        different processing of the results, based on the place the tool is used.
        """
        graph = SessionReplayFilterOptionsGraph(team=self._team, user=self._user)
        pretty_filters = json.dumps(self.context.get("current_filters", {}), indent=2)
        user_prompt = USER_FILTER_OPTIONS_PROMPT.format(change=change, current_filters=pretty_filters)
        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            "billable": True,
            **self.context,
        }
        result = await graph.compile_full_graph().ainvoke(graph_context)
        return result

    async def _arun_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        result = await self._invoke_graph(change)
        if type(result["output"]) is not MaxRecordingUniversalFilters:
            content = result["intermediate_steps"][-1][0].tool_input
            filters = MaxRecordingUniversalFilters.model_validate(self.context.get("current_filters", {}))
        else:
            try:
                content = "✅ Updated session recordings filters."
                filters = MaxRecordingUniversalFilters.model_validate(result["output"])
            except Exception as e:
                raise ValueError(f"Failed to generate MaxRecordingUniversalFilters: {e}")
        return content, filters
