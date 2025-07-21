from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from .prompts import (
    AI_FILTER_INITIAL_PROMPT,
    AI_FILTER_PROPERTIES_PROMPT,
    AI_FILTER_REQUEST_PROMPT,
    QuestionResponse,
)
from posthog.schema import MaxRecordingUniversalFilters
from ee.hogai.tool import MaxTool
import json
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.exceptions import OutputParserException
import structlog

logger = structlog.getLogger(__name__)


class SearchSessionRecordingsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to recordings filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class SearchSessionRecordingsTool(MaxTool):
    name: str = "search_session_recordings"
    description: str = (
        "Update session recordings filters on this page, in order to search for session recordings by any criteria."
    )
    thinking_message: str = "Coming up with session recordings filters"
    root_system_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    def _run_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        model = ChatOpenAI(model="gpt-4.1", temperature=0.2).with_retry()

        prompt = ChatPromptTemplate(
            [
                ("system", AI_FILTER_INITIAL_PROMPT),
                ("system", AI_FILTER_PROPERTIES_PROMPT),
                ("human", AI_FILTER_REQUEST_PROMPT),
            ],
            template_format="mustache",
        )

        chain = prompt | model

        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `search_session_recordings` tool")

        current_filters = self.context["current_filters"]

        if isinstance(current_filters, str):
            current_filters = json.loads(current_filters)

        result = chain.invoke(
            {
                "change": change,
                "current_filters": json.dumps(current_filters, indent=2),
                "recording_filter_schema": json.dumps(MaxRecordingUniversalFilters.model_json_schema(), indent=2),
            }
        )

        try:
            parser = JsonOutputParser()
            parsed_data = parser.parse(str(result.content))

            if "question" in parsed_data:
                question_response = QuestionResponse.model_validate(parsed_data)
                return question_response.question, MaxRecordingUniversalFilters.model_validate_json(current_filters)

            validated_data = MaxRecordingUniversalFilters.model_validate(parsed_data)
        except (ValidationError, OutputParserException) as e:
            logger.exception("Error generating filters", error=e)
            return "Could not generate filters. Please try again.", MaxRecordingUniversalFilters.model_validate_json(
                current_filters
            )

        return "✅ Updated session recordings filters.", validated_data
