from pydantic import BaseModel, Field

from .prompts import (
    AI_FILTER_INITIAL_PROMPT,
    AI_FILTER_PROPERTIES_PROMPT,
    AI_FILTER_REQUEST_PROMPT,
)
from ee.hogai.tool import MaxTool
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from typing import Any
from posthog.models.team.team import Team
from posthog.models.user import User
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from posthog.schema import MaxRecordingUniversalFilters

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
        # model = (
        #     ChatOpenAI(model="gpt-4o", temperature=0.2)
        #     .with_structured_output(MaxRecordingUniversalFilters, include_raw=False)
        #     .with_retry()
        # )

        # prompt = ChatPromptTemplate(
        #     [
        #         ("system", AI_FILTER_INITIAL_PROMPT + AI_FILTER_PROPERTIES_PROMPT),
        #         ("human", AI_FILTER_REQUEST_PROMPT),
        #     ],
        #     template_format="mustache",
        # )

        # chain = prompt | model

        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `search_session_recordings` tool")
        
        if not self._team or not self._user:
            raise ValueError("Team and User are required for the search_session_recordings tool")
        # print(f"DEBUG: current_filters: {self.context.get('current_filters', 'NOT_FOUND')}")
        
        # Initialize and use the FilterOptionsGraph
        graph = FilterOptionsGraph(team=self._team, user=self._user)
        
        # Debug the inputs being passed to the graph
        graph_input = {
            "change": change,
            "filter_options_dict": None,  # Initialize missing state field  
            "messages": [],  # Initialize missing state field
            "root_tool_call_id": "", 
            **self.context
        }

        graph_result = graph.compile_full_graph().invoke(graph_input)

        # Check if this is a help request (filter_options_dict is None but has messages)
        if graph_result.get("filter_options_dict") is None and graph_result.get("messages"):
            messages = graph_result["messages"]
            help_content = "I need more information to proceed."
            
            # Extract the actual help message from the graph result
            for message in messages:
                if hasattr(message, 'content') and message.content:
                    help_content = message.content
                    break
            
            print(f"DEBUG: Detected help request with content: {help_content}")
            
            # Return the help message and current filters unchanged
            current_filters = self.context.get("current_filters", {})
            current_filters_obj = MaxRecordingUniversalFilters.model_validate(current_filters)
            return help_content, current_filters_obj
            
        # Convert to the expected type
        try:
            result = MaxRecordingUniversalFilters.model_validate(graph_result["filter_options_dict"]["data"])
        except Exception as e:
            raise ValueError(f"Failed to convert filter options to MaxRecordingUniversalFilters: {e}")
        
        return "✅ Updated session recordings filters.", result
