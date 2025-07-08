from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from posthog.schema import ErrorTrackingSceneToolOutput
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from .prompts import (
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
    ERROR_TRACKING_SYSTEM_PROMPT,
    PREFER_FILTERS_PROMPT,
)
from ee.hogai.tool import MaxTool
from typing import Optional
import json
import re


class UpdateIssueQueryArgs(BaseModel):
    change: str = Field(description="The specific change to be made to issue filters, briefly described.")


class ErrorTrackingSceneTool(MaxTool):
    name: str = "search_error_tracking_issues"
    description: str = "Update the error tracking issue list, editing search query, property filters, date ranges, assignee and status filters."
    thinking_message: str = "Updating your error tracking filters..."
    root_system_prompt_template: str = "Current issue filters are: {current_query}"
    args_schema: type[BaseModel] = UpdateIssueQueryArgs

    def _run_impl(self, change: str) -> tuple[str, ErrorTrackingSceneToolOutput]:
        if "current_query" not in self.context:
            raise ValueError("Context `current_query` is required for the `search_error_tracking_issues` tool")

        current_query = self.context.get("current_query")
        system_content = (
            ERROR_TRACKING_SYSTEM_PROMPT
            + "<system_task>"
            + ERROR_TRACKING_FILTER_INITIAL_PROMPT
            + "</system_task>"
            + f"\n\n Current issue filters are: {current_query}\n\n"
            + "<properties_taxonomy>"
            + ERROR_TRACKING_FILTER_PROPERTIES_PROMPT
            + "</properties_taxonomy>"
            + "<prefer_filters>"
            + PREFER_FILTERS_PROMPT
            + "</prefer_filters>"
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
        return ChatOpenAI(model="gpt-4.1", temperature=0.3, disable_streaming=True)

    def _parse_output(self, output: str) -> ErrorTrackingSceneToolOutput:
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

        return ErrorTrackingSceneToolOutput(**data)
