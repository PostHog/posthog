from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from .prompts import (
    AI_FILTER_INITIAL_PROMPT,
    AI_FILTER_PROPERTIES_PROMPT,
    AI_FILTER_REQUEST_PROMPT,
)
from posthog.schema import MaxRecordingUniversalFilters
from ee.hogai.tool import MaxTool
import json
from langchain_core.output_parsers import JsonOutputParser


class SearchSessionRecordingsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to recordings filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class QuestionResponse(BaseModel):
    question: str = Field(description="The question that the user is asking.")


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
            ChatOpenAI(model="gpt-4.1", temperature=0.2)
            # .with_structured_output(MaxRecordingUniversalFilters, include_raw=False)
            .with_retry()
        )

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

        and_filter_example = json.dumps(
            MaxRecordingUniversalFilters(
                **{
                    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gte"}],
                    "date_from": "-3d",
                    "date_to": None,
                    "filter_group": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "$browser", "type": "person", "value": ["Mobile"], "operator": "exact"}
                                ],
                            },
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "$login_page", "type": "person", "value": ["true"], "operator": "exact"}
                                ],
                            },
                        ],
                    },
                }
            ).model_dump_json(indent=2)
        )

        or_filter_example = json.dumps(
            MaxRecordingUniversalFilters(
                **{
                    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gte"}],
                    "date_from": "-3d",
                    "date_to": None,
                    "filter_group": {  # Add them to the same filter group
                        "type": "OR",  # type of the filter group, OR means at least one of the filters must be true
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "$browser", "type": "person", "value": ["Mobile"], "operator": "exact"}
                                ],
                            },
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "$login_page", "type": "person", "value": ["true"], "operator": "exact"}
                                ],
                            },
                        ],
                    },
                }
            ).model_dump_json(indent=2)
        )

        multiple_filters_example = MaxRecordingUniversalFilters(
            **{
                "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "exact"}],
                "date_from": "-3d",
                "date_to": None,
                "filter_group": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "$browser", "type": "person", "value": ["Mobile"], "operator": "exact"}],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "$login_page", "type": "event", "value": ["true"], "operator": "exact"}],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {"key": "$geo_ip_location", "type": "person", "value": ["Munich"], "operator": "exact"},
                                {
                                    "key": "$geo_ip_location",
                                    "type": "person",
                                    "value": ["Istanbul"],
                                    "operator": "exact",
                                },
                            ],
                        },
                    ],
                },
            }
        ).model_dump_json(indent=2)

        default_filter_example = json.dumps(
            MaxRecordingUniversalFilters(
                **{
                    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "exact"}],
                    "date_from": "-3d",
                    "date_to": None,
                    "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
                }
            ).model_dump_json(indent=2)
        )

        result = chain.invoke(
            {
                "change": change,
                **self.context,
                "recording_filter_schema": json.dumps(MaxRecordingUniversalFilters.model_json_schema(), indent=2),
                "and_filter_example": and_filter_example,
                "or_filter_example": or_filter_example,
                "multiple_filters_example": multiple_filters_example,
                "default_filter_example": default_filter_example,
            }
        )

        parser = JsonOutputParser()
        parsed_data = parser.parse(str(result.content))

        if "question" in parsed_data:
            question_response = QuestionResponse.model_validate(parsed_data)
            return question_response.question, MaxRecordingUniversalFilters.model_validate_json(
                self.context["current_filters"]
            )

        try:
            validated_data = MaxRecordingUniversalFilters.model_validate(parsed_data)
        except ValidationError:
            return "Could not generate filters. Please try again.", MaxRecordingUniversalFilters.model_validate_json(
                self.context["current_filters"]
            )

        return "✅ Updated session recordings filters.", validated_data
