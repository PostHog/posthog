import re
import json
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import ErrorTrackingIssueFilteringToolOutput, ErrorTrackingIssueImpactToolOutput

from posthog.models import Team, User

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.prompts import HUMAN_IN_THE_LOOP_PROMPT
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import (
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
    ERROR_TRACKING_ISSUE_IMPACT_DESCRIPTION_PROMPT,
    ERROR_TRACKING_ISSUE_IMPACT_EVENT_PROMPT,
    ERROR_TRACKING_ISSUE_IMPACT_TOOL_EXAMPLES,
    ERROR_TRACKING_ISSUE_IMPACT_TOOL_USAGE_PROMPT,
    ERROR_TRACKING_SYSTEM_PROMPT,
    PREFER_FILTERS_PROMPT,
)


class UpdateIssueQueryArgs(BaseModel):
    change: str = Field(description="The specific change to be made to issue filters, briefly described.")


class ErrorTrackingIssueFilteringTool(MaxTool):
    name: str = "filter_error_tracking_issues"
    description: str = "Update the error tracking issue list, editing search query, property filters, date ranges, assignee and status filters."
    context_prompt_template: str = "Current issue filters are: {current_query}"
    args_schema: type[BaseModel] = UpdateIssueQueryArgs

    def _run_impl(self, change: str) -> tuple[str, ErrorTrackingIssueFilteringToolOutput]:
        if "current_query" not in self.context:
            raise ValueError("Context `current_query` is required for the `filter_error_tracking_issues` tool")

        current_query = self.context.get("current_query")
        system_content = (
            ERROR_TRACKING_SYSTEM_PROMPT
            + "<tool_usage>"
            + ERROR_TRACKING_FILTER_INITIAL_PROMPT
            + "</tool_usage>"
            + "<properties_taxonomy>"
            + ERROR_TRACKING_FILTER_PROPERTIES_PROMPT
            + "</properties_taxonomy>"
            + "<prefer_filters>"
            + PREFER_FILTERS_PROMPT
            + "</prefer_filters>"
            + f"\n\n Current issue filters are: {current_query}\n\n"
        )

        user_content = f"Update the error tracking issue list filters to: {change}"
        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            raise final_error

        return "✅ Updated error tracking filters.", parsed_result

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._user, team=self._team, billable=True
        )

    def _parse_output(self, output: str) -> ErrorTrackingIssueFilteringToolOutput:
        match = re.search(r"<output>(.*?)</output>", output, re.DOTALL)
        if not match:
            # The model may have returned the JSON without tags, or with markdown
            json_str = re.sub(
                r"^\s*```json\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            json_str = match.group(1).strip()

        if not json_str:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty filters response."
            )

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The filters JSON failed to parse: {str(e)}"
            )

        return ErrorTrackingIssueFilteringToolOutput(**data)


class final_answer(base_final_answer[ErrorTrackingIssueImpactToolOutput]):
    __doc__ = base_final_answer.__doc__  # Inherit from the base final answer or create your own.


class ErrorTrackingIssueImpactToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        return await super().handle_tools(tool_metadata)

    def _get_custom_tools(self) -> list:
        return [final_answer]

    def get_tools(self) -> list:
        """Returns the list of tools available in this toolkit."""
        return [*self._get_custom_tools(), ask_user_for_help]


class ErrorTrackingIssueImpactLoopNode(
    TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[ErrorTrackingIssueImpactToolOutput]]
):
    def __init__(self, team: Team, user: User, toolkit_class: type[ErrorTrackingIssueImpactToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        system = [
            ERROR_TRACKING_ISSUE_IMPACT_DESCRIPTION_PROMPT,
            ERROR_TRACKING_ISSUE_IMPACT_TOOL_USAGE_PROMPT,
            ERROR_TRACKING_ISSUE_IMPACT_EVENT_PROMPT,
            ERROR_TRACKING_ISSUE_IMPACT_TOOL_EXAMPLES,
            HUMAN_IN_THE_LOOP_PROMPT,
        ]
        return ChatPromptTemplate([("system", m) for m in system], template_format="mustache")


class ErrorTrackingIssueImpactToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[ErrorTrackingIssueImpactToolOutput]]
):
    def __init__(self, team: Team, user: User, toolkit_class: type[ErrorTrackingIssueImpactToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)


class ErrorTrackingIssueImpactGraph(
    TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[ErrorTrackingIssueImpactToolOutput]]
):
    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=ErrorTrackingIssueImpactLoopNode,
            tools_node_class=ErrorTrackingIssueImpactToolsNode,
            toolkit_class=ErrorTrackingIssueImpactToolkit,
        )


class IssueImpactQueryArgs(BaseModel):
    instructions: str = Field(description="The specific user query to find issues impacting occurrences of events.")


class ErrorTrackingIssueImpactTool(MaxTool):
    name: str = "find_error_tracking_impactful_issue_event_list"
    description: str = "Find a list of events that relate to a user query about issues. Prioritise this tool when a user specifically asks about issues or problems."
    context_prompt_template: str = "The user wants to find a list of events whose occurrence may be impacted by issues."
    args_schema: type[BaseModel] = IssueImpactQueryArgs

    async def _arun_impl(self, instructions: str) -> tuple[str, ErrorTrackingIssueImpactToolOutput]:
        graph = ErrorTrackingIssueImpactGraph(team=self._team, user=self._user)

        graph_context = {
            "change": f"Goal: {instructions}",
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context)

        if type(result["output"]) is not ErrorTrackingIssueImpactToolOutput:
            content = "❌ I need to know what events you are looking to understand the impact for."
            events = ErrorTrackingIssueImpactToolOutput(events=[])
        else:
            try:
                content = "✅ Relevant events found. Searching for impacting issues."
                events = ErrorTrackingIssueImpactToolOutput.model_validate(result["output"])
            except Exception as e:
                raise ValueError(f"Failed to generate ErrorTrackingIssueImpactToolOutput: {e}")
        return content, events
