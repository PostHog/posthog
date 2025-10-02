from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import RevenueAnalyticsAssistantGoalsOutput, RevenueAnalyticsGoal

from posthog.models import Team, User
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import GOALS_DESCRIPTION_PROMPT, GOALS_EXAMPLES_PROMPT


class final_answer(base_final_answer[RevenueAnalyticsAssistantGoalsOutput]):
    __doc__ = base_final_answer.__doc__


class add_revenue_goal(BaseModel):
    """Add a new revenue goal."""

    goal: RevenueAnalyticsGoal = Field(description="Goal object. Make sure due_date is in YYYY-MM-DD format")


class update_revenue_goal(BaseModel):
    """Update an existing revenue goal."""

    goal_name: str = Field(description="Name of the goal to update")
    new_goal: RevenueAnalyticsGoal = Field(description="New goal object we should update the goal with.")


class remove_revenue_goal(BaseModel):
    """Remove a revenue goal."""

    goal_name: str = Field(description="Name of the goal to remove")


class list_revenue_goals(BaseModel):
    """List all revenue goals."""


class RevenueGoalsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team)

    def handle_tools(self, tool_name: str, tool_input) -> tuple[str, str]:
        """Handle custom tool execution."""
        if tool_name == "add_revenue_goal":
            result = self._add_revenue_goal(tool_input.arguments)
            return tool_name, result
        elif tool_name == "update_revenue_goal":
            result = self._update_revenue_goal(tool_input.arguments)
            return tool_name, result
        elif tool_name == "remove_revenue_goal":
            result = self._remove_revenue_goal(tool_input.arguments)
            return tool_name, result
        elif tool_name == "list_revenue_goals":
            result = self._list_revenue_goals()
            return tool_name, result

        return super().handle_tools(tool_name, tool_input)

    def _get_custom_tools(self) -> list:
        return [final_answer, add_revenue_goal, update_revenue_goal, remove_revenue_goal, list_revenue_goals]

    def get_tools(self) -> list:
        """Returns the list of tools available in this toolkit."""
        return [*self._get_custom_tools(), ask_user_for_help]

    def _add_revenue_goal(self, args: add_revenue_goal) -> str:
        """Add a new revenue goal."""
        try:
            config, _ = TeamRevenueAnalyticsConfig.objects.get_or_create(team=self._team)
            current_goals = config.goals

            # Add the new goal
            current_goals.append(args.goal)
            config.goals = [goal.model_dump() for goal in current_goals]
            config.save()
            config.team.save()  # Force team cache to update
            return f"✅ Added revenue goal: {args.goal.name} (${args.goal.goal:,.2f} due {args.goal.due_date})"
        except Exception as e:
            return f"❌ Failed to add revenue goal: {str(e)}"

    def _update_revenue_goal(self, args: update_revenue_goal) -> str:
        """Update an existing revenue goal."""
        try:
            config, _ = TeamRevenueAnalyticsConfig.objects.get_or_create(team=self._team)
            current_goals = config.goals

            # Find and update the goal
            updated = False
            for i, existing_goal in enumerate(current_goals):
                if existing_goal.name == args.goal_name:
                    current_goals[i] = args.new_goal
                    updated = True
                    break

            if updated:
                config.goals = [goal.model_dump() for goal in current_goals]
                config.save()
                config.team.save()  # Force team cache to update
                return f"✅ Updated revenue goal: {args.goal_name}"
            else:
                return f"❌ Goal '{args.goal_name}' not found"
        except Exception as e:
            return f"❌ Failed to update revenue goal: {str(e)}"

    def _remove_revenue_goal(self, args: remove_revenue_goal) -> str:
        """Remove a revenue goal."""
        try:
            config, _ = TeamRevenueAnalyticsConfig.objects.get_or_create(team=self._team)
            current_goals = config.goals

            # Filter out the goal with the specified name
            updated_goals = [goal for goal in current_goals if goal.name != args.goal_name]

            if len(updated_goals) != len(current_goals):
                config.goals = [goal.model_dump() for goal in updated_goals]
                config.save()
                config.team.save()  # Force team cache to update
                return f"✅ Removed revenue goal: {args.goal_name}"
            else:
                return f"❌ Goal '{args.goal_name}' not found"
        except Exception as e:
            return f"❌ Failed to remove revenue goal: {str(e)}"

    def _list_revenue_goals(self) -> str:
        """List all revenue goals."""
        try:
            config, _ = TeamRevenueAnalyticsConfig.objects.get_or_create(team=self._team)
            goals = config.goals

            if not goals:
                return "No revenue goals found."

            goals_text = "\n".join(
                [f"- {goal.name}: ${goal.goal:,.2f} ({goal.mrr_or_gross.value}) due {goal.due_date}" for goal in goals]
            )
            return f"Current revenue goals:\n{goals_text}"
        except Exception as e:
            return f"❌ Failed to list revenue goals: {str(e)}"


class RevenueGoalsNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantGoalsOutput]]):
    """Node for managing revenue goals."""

    def __init__(self, team: Team, user: User, toolkit_class: type[RevenueGoalsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.REVENUE_GOALS

    def _get_system_prompt(self) -> ChatPromptTemplate:
        all_messages = [GOALS_DESCRIPTION_PROMPT, GOALS_EXAMPLES_PROMPT]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")


class RevenueGoalsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantGoalsOutput]]
):
    """Tools node for revenue goals management."""

    def __init__(self, team: Team, user: User, toolkit_class: type[RevenueGoalsToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.REVENUE_GOALS_TOOLS


class RevenueGoalsGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[RevenueAnalyticsAssistantGoalsOutput]]):
    """Graph for managing revenue goals."""

    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=RevenueGoalsNode,
            tools_node_class=RevenueGoalsToolsNode,
            toolkit_class=RevenueGoalsToolkit,
        )


class ManageRevenueGoalsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to the revenue goals, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )
