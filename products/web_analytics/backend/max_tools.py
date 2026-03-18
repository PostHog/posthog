import json
import logging
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import WebAnalyticsAssistantFilters

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models import Team, User
from posthog.queries.property_values import get_person_property_values_for_key, get_property_values_for_key
from posthog.sync import database_sync_to_async
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from ee.hogai.chat_agent.taxonomy.agent import TaxonomyAgent
from ee.hogai.chat_agent.taxonomy.format import enrich_props_with_descriptions, format_properties_xml
from ee.hogai.chat_agent.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.chat_agent.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyErrorMessages
from ee.hogai.chat_agent.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    COMPARE_FILTER_PROMPT,
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PATH_CLEANING_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
)


class final_answer(base_final_answer[WebAnalyticsAssistantFilters]):
    __doc__ = base_final_answer.__doc__


class retrieve_web_analytics_property_values(BaseModel):
    """
    Use this tool to lookup values for a web analytics property (event, session, or person properties).
    """

    property_key: str = Field(
        description="The key of the property to look up values for (e.g., $host, $browser, $entry_utm_source)",
    )
    property_type: Literal["event", "session", "person"] = Field(
        description="The type of property: 'event' for web event properties, 'session' for session properties, 'person' for person properties",
    )


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class WebAnalyticsFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        results = {}
        unhandled_tools = {}
        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "retrieve_web_analytics_property_values":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._retrieve_web_analytics_property_values(
                            tool_input.arguments.property_key,  # type: ignore
                            tool_input.arguments.property_type,  # type: ignore
                        )
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    def _get_custom_tools(self) -> list:
        return [final_answer, retrieve_web_analytics_property_values]

    def get_tools(self) -> list:
        return [*self._get_custom_tools(), ask_user_for_help]

    async def _retrieve_web_analytics_property_values(
        self, property_name: str, property_type: Literal["event", "session", "person"]
    ) -> str:
        if property_type == "person":
            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                values = await database_sync_to_async(get_person_property_values_for_key)(
                    property_name, self._team, value=None
                )
        elif property_type in ("event", "session"):
            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                values = await database_sync_to_async(get_property_values_for_key)(
                    property_name, self._team, event_names=None, value=None
                )
        else:
            return TaxonomyErrorMessages.property_not_found(property_name, property_type)

        return self._format_property_values(property_name, values, sample_count=len(values))


class WebAnalyticsFilterNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]):
    def __init__(self, team: Team, user: User, toolkit_class: type[WebAnalyticsFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.WEB_ANALYTICS_FILTER

    def _filter_properties_by_type(self, property_group: str) -> list[tuple[str, str]]:
        """Extract properties from CORE_FILTER_DEFINITIONS_BY_GROUP for a given property group."""
        return [
            (prop_name, prop["type"])
            for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP.get(property_group, {}).items()
            if prop.get("type") is not None
        ]

    def _get_system_prompt(self) -> ChatPromptTemplate:
        event_properties = self._filter_properties_by_type("event_properties")
        session_properties = self._filter_properties_by_type("session_properties")
        person_properties = self._filter_properties_by_type("person_properties")

        all_messages = [
            PRODUCT_DESCRIPTION_PROMPT,
            FILTER_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT,
            f"<event_properties>\n{format_properties_xml(enrich_props_with_descriptions('event', event_properties))}\n</event_properties>",
            f"<session_properties>\n{format_properties_xml(enrich_props_with_descriptions('session', session_properties))}\n</session_properties>",
            f"<person_properties>\n{format_properties_xml(enrich_props_with_descriptions('person', person_properties))}\n</person_properties>",
            PATH_CLEANING_PROMPT,
            COMPARE_FILTER_PROMPT,
            DATE_FIELDS_PROMPT,
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")


class WebAnalyticsFilterOptionsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]
):
    def __init__(self, team: Team, user: User, toolkit_class: type[WebAnalyticsFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.WEB_ANALYTICS_FILTER_OPTIONS_TOOLS


class WebAnalyticsFilterOptionsGraph(
    TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]
):
    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=WebAnalyticsFilterNode,
            tools_node_class=WebAnalyticsFilterOptionsToolsNode,
            toolkit_class=WebAnalyticsFilterOptionsToolkit,
        )


class FilterWebAnalyticsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to the web analytics filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class FilterWebAnalyticsTool(MaxTool):
    name: str = "filter_web_analytics"
    description: str = """
    - Update web analytics filters on this page, in order to better analyze web traffic and user behavior.
    - When to use the tool:
      * When the user asks to update web analytics filters
        - "update" synonyms: "change", "modify", "adjust", and similar
        - "web analytics" synonyms: "traffic", "visitors", "pageviews", and similar
      * When the user asks to search for web analytics or traffic data
        - "search for" synonyms: "find", "look up", "show me", and similar
      * When the user asks to enable/disable path cleaning or comparison
    """
    context_prompt_template: str = "Current web analytics filters are: {current_filters}"
    args_schema: type[BaseModel] = FilterWebAnalyticsArgs

    def get_required_resource_access(self):
        return [("web_analytics", "viewer")]

    async def _invoke_graph(self, change: str) -> dict[str, Any] | Any:
        graph = WebAnalyticsFilterOptionsGraph(team=self._team, user=self._user)
        pretty_filters = json.dumps(self.context.get("current_filters", {}), indent=2)
        user_prompt = USER_FILTER_OPTIONS_PROMPT.format(change=change, current_filters=pretty_filters)
        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }
        result = await graph.compile_full_graph().ainvoke(graph_context)
        return result

    async def _arun_impl(self, change: str) -> tuple[str, WebAnalyticsAssistantFilters]:
        result = await self._invoke_graph(change)
        if type(result["output"]) is not WebAnalyticsAssistantFilters:
            content = result["intermediate_steps"][-1][0].tool_input
            filters = WebAnalyticsAssistantFilters.model_validate(self.context.get("current_filters", {}))
        else:
            try:
                content = "✅ Updated web analytics filters."
                filters = WebAnalyticsAssistantFilters.model_validate(result["output"])
            except Exception as e:
                raise ValueError(f"Failed to generate WebAnalyticsAssistantFilters: {e}")
        return content, filters
