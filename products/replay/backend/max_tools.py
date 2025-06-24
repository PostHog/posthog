from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .prompts import (
    AI_FILTER_INITIAL_PROMPT,
    AI_FILTER_PROPERTIES_PROMPT,
    AI_FILTER_REQUEST_PROMPT,
)
from posthog.schema import MaxRecordingUniversalFilters
from ee.hogai.tool import MaxTool


class SearchSessionRecordingsArgs(BaseModel):
    change: str = Field(description="The specific change to be made to recordings filters, briefly described.")


class SearchSessionRecordingsTool(MaxTool):
    name: str = "search_session_recordings"
    description: str = (
        "Update session recordings filters on this page, in order to search for session recordings by any criteria."
    )
    thinking_message: str = "Coming up with session recordings filters"
    root_system_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    def _run_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        model = (
            ChatOpenAI(model="gpt-4o", temperature=0.2)
            .with_structured_output(MaxRecordingUniversalFilters, include_raw=False)
            .with_retry()
        )

        prompt = ChatPromptTemplate(
            [
                ("system", AI_FILTER_INITIAL_PROMPT + AI_FILTER_PROPERTIES_PROMPT),
                ("human", AI_FILTER_REQUEST_PROMPT),
            ],
            template_format="mustache",
        )

        chain = prompt | model

        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `search_session_recordings` tool")

        result = chain.invoke({"change": change, **self.context})
        assert isinstance(result, MaxRecordingUniversalFilters)

        return "✅ Updated session recordings filters.", result
