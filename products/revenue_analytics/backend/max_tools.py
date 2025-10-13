import json
from typing import Any

from pydantic import BaseModel

from posthog.schema import RevenueAnalyticsAssistantFilters, RevenueAnalyticsAssistantGoalsOutput

from products.revenue_analytics.backend.ai.tools.filter_revenue_analytics import (
    USER_FILTER_OPTIONS_PROMPT,
    FilterRevenueAnalyticsArgs,
    RevenueAnalyticsFilterOptionsGraph,
)
from products.revenue_analytics.backend.ai.tools.revenue_goals import (
    USER_GOALS_PROMPT,
    ManageRevenueGoalsArgs,
    RevenueGoalsGraph,
)

from ee.hogai.tool import MaxTool


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
    thinking_message: str = "Coming up with filters"
    root_system_prompt_template: str = "Current revenue analytics filters are: {current_filters}"
    args_schema: type[BaseModel] = FilterRevenueAnalyticsArgs
    show_tool_call_message: bool = False

    async def _invoke_graph(self, change: str) -> dict[str, Any] | Any:
        """
        Reusable method to call graph to avoid code/prompt duplication and enable
        different processing of the results, based on the place the tool is used.
        """
        graph = RevenueAnalyticsFilterOptionsGraph(team=self._team, user=self._user)
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

    async def _arun_impl(self, change: str) -> tuple[str, RevenueAnalyticsAssistantFilters]:
        result = await self._invoke_graph(change)
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


class ManageRevenueGoalsTool(MaxTool):
    name: str = "manage_revenue_goals"
    description: str = """
    - Add, update, remove, or list revenue goals for the team.
    - When to use the tool:
      * When the user asks to add a new revenue goal
      * When the user asks to update an existing revenue goal
      * When the user asks to remove a revenue goal
      * When the user asks to list current revenue goals
    """
    thinking_message: str = "Managing revenue goals"
    root_system_prompt_template: str = "Current revenue goals are: {current_goals}"
    args_schema: type[BaseModel] = ManageRevenueGoalsArgs
    show_tool_call_message: bool = False

    async def _invoke_graph(self, change: str) -> dict[str, Any] | Any:
        """
        Reusable method to call graph to avoid code/prompt duplication and enable
        different processing of the results, based on the place the tool is used.
        """
        graph = RevenueGoalsGraph(team=self._team, user=self._user)
        user_prompt = USER_GOALS_PROMPT.format(change=change)
        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }
        result = await graph.compile_full_graph().ainvoke(graph_context)
        return result

    async def _arun_impl(self, change: str) -> tuple[str, RevenueAnalyticsAssistantGoalsOutput]:
        result = await self._invoke_graph(change)
        if type(result["output"]) is not RevenueAnalyticsAssistantGoalsOutput:
            content = result["intermediate_steps"][-1][0].tool_input
            output = RevenueAnalyticsAssistantGoalsOutput(goals=None)
        else:
            try:
                content = "✅ Revenue goals action completed."
                output = result["output"]
            except Exception as e:
                raise ValueError(f"Failed to process revenue goals result: {e}")
        return content, output
