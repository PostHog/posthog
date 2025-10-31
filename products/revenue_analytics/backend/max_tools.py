import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import RevenueAnalyticsAssistantFilters

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from products.revenue_analytics.backend.api import find_values_for_revenue_analytics_property

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.format import enrich_props_with_descriptions, format_properties_xml
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyErrorMessages
from ee.hogai.graph.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool, MaxToolArgs
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
)


class final_answer(base_final_answer[RevenueAnalyticsAssistantFilters]):
    __doc__ = base_final_answer.__doc__


class retrieve_revenue_analytics_property_values(BaseModel):
    """
    Use this tool to lookup values for a revenue analytics property.
    """

    property_key: str = Field(
        description="The key of the property to look up values for",
        pattern=r"^revenue_analytics_[a-zA-Z0-9_.]+$",
    )


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class RevenueAnalyticsFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        """Handle custom tool execution."""
        results = {}
        unhandled_tools = {}
        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "retrieve_revenue_analytics_property_values":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._retrieve_revenue_analytics_property_values(
                            tool_input.arguments.property_key  # type: ignore
                        )
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    def _get_custom_tools(self) -> list:
        return [final_answer, retrieve_revenue_analytics_property_values]

    # Do not include all of the default taxonomy tools, only use the ones we're defining here
    # plus the generally useful tools like `ask_user_for_help`
    def get_tools(self) -> list:
        """Returns the list of tools available in this toolkit."""
        return [*self._get_custom_tools(), ask_user_for_help]

    async def _retrieve_revenue_analytics_property_values(self, property_name: str) -> str:
        """
        Revenue analytics properties come from Clickhouse so let's run a separate query here.
        """
        if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["revenue_analytics_properties"]:
            return TaxonomyErrorMessages.property_not_found(property_name, "revenue_analytics")

        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            values = await database_sync_to_async(find_values_for_revenue_analytics_property)(property_name, self._team)

        return self._format_property_values(property_name, values, sample_count=len(values))


class RevenueAnalyticsFilterNode(
    TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantFilters]]
):
    """Node for generating filtering options for revenue analytics."""

    def __init__(self, team: Team, user: User, toolkit_class: type[RevenueAnalyticsFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.REVENUE_ANALYTICS_FILTER

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get default system prompts. Override in subclasses for custom prompts."""
        all_messages = [
            PRODUCT_DESCRIPTION_PROMPT,
            FILTER_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT.format(
                revenue_analytics_entity_values=format_properties_xml(
                    enrich_props_with_descriptions(
                        "revenue_analytics",
                        [
                            (prop_name, prop["type"])
                            for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP[
                                "revenue_analytics_properties"
                            ].items()
                            if prop.get("type") is not None
                        ],
                    )
                )
            ),
            DATE_FIELDS_PROMPT,
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")


class RevenueAnalyticsFilterOptionsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantFilters]]
):
    """Node for generating filtering options for revenue analytics."""

    def __init__(self, team: Team, user: User, toolkit_class: type[RevenueAnalyticsFilterOptionsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.REVENUE_ANALYTICS_FILTER_OPTIONS_TOOLS


class RevenueAnalyticsFilterOptionsGraph(
    TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantFilters]]
):
    """Graph for generating filtering options for revenue analytics."""

    def __init__(self, team: Team, user: User, tool_call_id: str):
        super().__init__(
            team,
            user,
            tool_call_id,
            loop_node_class=RevenueAnalyticsFilterNode,
            tools_node_class=RevenueAnalyticsFilterOptionsToolsNode,
            toolkit_class=RevenueAnalyticsFilterOptionsToolkit,
        )


class FilterRevenueAnalyticsArgs(MaxToolArgs):
    change: str = Field(
        description=(
            "The specific change to be made to the revenue analytics filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class FilterRevenueAnalyticsTool(MaxTool):
    name: str = "filter_revenue_analytics"
    description: str = """
    - Update revenue analytics filters on this page, in order to better represent the user's revenue.
    - When to use the tool:
      * When the user asks to update revenue analytics filters
        - "update" synonyms: "change", "modify", "adjust", and similar
        - "revenue analytics" synonyms: "revenue", "MRR", "growth", "churn", and similar
      * When the user asks to search for revenue analytics or revenue
        - "search for" synonyms: "find", "look up", and similar
    """
    context_prompt_template: str = "Current revenue analytics filters are: {current_filters}"
    args_schema: type[BaseModel] = FilterRevenueAnalyticsArgs

    async def _invoke_graph(self, change: str, tool_call_id: str) -> dict[str, Any] | Any:
        """
        Reusable method to call graph to avoid code/prompt duplication and enable
        different processing of the results, based on the place the tool is used.
        """
        graph = RevenueAnalyticsFilterOptionsGraph(team=self._team, user=self._user, tool_call_id=tool_call_id)
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

    async def _arun_impl(self, change: str, tool_call_id: str) -> tuple[str, RevenueAnalyticsAssistantFilters]:
        result = await self._invoke_graph(change, tool_call_id)
        if type(result["output"]) is not RevenueAnalyticsAssistantFilters:
            content = result["intermediate_steps"][-1][0].tool_input
            filters = RevenueAnalyticsAssistantFilters.model_validate(self.context.get("current_filters", {}))
        else:
            try:
                content = "✅ Updated revenue analytics filters."
                filters = RevenueAnalyticsAssistantFilters.model_validate(result["output"])
            except Exception as e:
                raise ValueError(f"Failed to generate RevenueAnalyticsAssistantFilters: {e}")
        return content, filters
