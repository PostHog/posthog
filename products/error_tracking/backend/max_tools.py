import re
import json
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from posthog.schema import ErrorTrackingIssueFilteringToolOutput

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import (
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
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

    def get_required_resource_access(self):
        return [("error_tracking", "viewer")]

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
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
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
