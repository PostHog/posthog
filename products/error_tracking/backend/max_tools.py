from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing import Optional, Any

from .prompts import (
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
    ERROR_TRACKING_FILTER_REQUEST_PROMPT,
)
from ee.hogai.tool import MaxTool


class UpdateIssueQueryArgs(BaseModel):
    change: str = Field(description="The specific change to be made to issue filters, briefly described.")


class ErrorTrackingFiltersOutput(BaseModel):
    search_query: Optional[str] = Field(
        default=None, description="Text search across error messages, stack traces, exception types"
    )
    status: Optional[str] = Field(
        default=None, description="Issue status: active, resolved, archived, pending_release, suppressed, all"
    )
    assignee: Optional[dict[str, Any]] = Field(default=None, description="Assignee with id and type (user/role)")
    date_range: Optional[dict[str, Any]] = Field(default=None, description="Date range with date_from and date_to")
    filter_test_accounts: Optional[bool] = Field(default=None, description="Whether to filter out test accounts")
    filter_group: Optional[dict[str, Any]] = Field(
        default=None, description="PropertyGroupFilter for structured property filtering"
    )


class CreateErrorTrackingFiltersTool(MaxTool):
    name: str = "create_error_tracking_filters"
    description: str = "Update error tracking issue filters on this page to search for specific errors by any criteria."
    thinking_message: str = "Updating your error tracking filters..."
    root_system_prompt_template: str = "Current issue filters are: {current_filters}"
    args_schema = UpdateIssueQueryArgs

    def _run_impl(self, change: str) -> tuple[str, ErrorTrackingFiltersOutput]:
        model = (
            ChatOpenAI(model="gpt-4o", temperature=0.2)
            .with_structured_output(ErrorTrackingFiltersOutput, include_raw=False)
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

        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `create_error_tracking_filters` tool")

        result = chain.invoke({"change": change, **self.context})
        assert isinstance(result, ErrorTrackingFiltersOutput)

        return "✅ Updated error tracking filters.", result
