from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from posthog.schema import ErrorTrackingSceneToolOutput

from .prompts import (
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
    ERROR_TRACKING_FILTER_REQUEST_PROMPT,
)
from ee.hogai.tool import MaxTool


class UpdateIssueQueryArgs(BaseModel):
    change: str = Field(description="The specific change to be made to issue filters, briefly described.")


class ErrorTrackingSceneTool(MaxTool):
    name: str = "search_error_tracking_issues"
    description: str = "Update the error tracking issue list, editing search query, property filters, date ranges, assignee and status filters."
    thinking_message: str = "Updating your error tracking filters..."
    root_system_prompt_template: str = "Current issue filters are: {current_query}"
    args_schema: type[BaseModel] = UpdateIssueQueryArgs

    def _run_impl(self, change: str) -> tuple[str, ErrorTrackingSceneToolOutput]:
        model = (
            ChatOpenAI(model="gpt-4o", temperature=0.2)
            .with_structured_output(ErrorTrackingSceneToolOutput, include_raw=False)
            .with_retry()
        )

        prompt = ChatPromptTemplate(
            [
                ("system", ERROR_TRACKING_FILTER_INITIAL_PROMPT + ERROR_TRACKING_FILTER_PROPERTIES_PROMPT),
                ("human", ERROR_TRACKING_FILTER_REQUEST_PROMPT),
            ],
            template_format="mustache",
        )

        chain = prompt | model

        if "current_query" not in self.context:
            raise ValueError("Context `current_query` is required for the `search_error_tracking_issues` tool")

        result = chain.invoke({"change": change, **self.context})
        assert isinstance(result, ErrorTrackingSceneToolOutput)

        return "✅ Updated error tracking filters.", result
