from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import RevenueAnalyticsAssistantFilters

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models import Team, User
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from products.revenue_analytics.backend.api import find_values_for_revenue_analytics_property

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.format import enrich_props_with_descriptions, format_properties_xml
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyErrorMessages
from ee.hogai.graph.taxonomy.tools import ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
)


class RevenueAnalyticsFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team)

    def handle_tools(self, tool_name: str, tool_input) -> tuple[str, str]:
        """Handle custom tool execution."""
        if tool_name == "retrieve_revenue_analytics_property_values":
            result = self._retrieve_revenue_analytics_property_values(tool_input.arguments.property_key)
            return tool_name, result

        return super().handle_tools(tool_name, tool_input)

    def _get_custom_tools(self) -> list:
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

        return [final_answer, retrieve_revenue_analytics_property_values]

    # Do not include all of the default taxonomy tools, only use the ones we're defining here
    # plus the generally useful tools like `ask_user_for_help`
    def get_tools(self) -> list:
        """Returns the list of tools available in this toolkit."""
        return [*self._get_custom_tools(), ask_user_for_help]

    def _retrieve_revenue_analytics_property_values(self, property_name: str) -> str:
        """
        Revenue analytics properties come from Clickhouse so let's run a separate query here.
        """
        if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["revenue_analytics_properties"]:
            return TaxonomyErrorMessages.property_not_found(property_name, "revenue_analytics")

        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            values = find_values_for_revenue_analytics_property(property_name, self._team)

        return self._format_property_values(values, sample_count=len(values))


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

    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=RevenueAnalyticsFilterNode,
            tools_node_class=RevenueAnalyticsFilterOptionsToolsNode,
            toolkit_class=RevenueAnalyticsFilterOptionsToolkit,
        )


class FilterRevenueAnalyticsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to the revenue analytics filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )
