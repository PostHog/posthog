import logging
from pydantic import BaseModel, Field
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from ee.hogai.tool import MaxTool, FilterProfile, register_filter_profile
from posthog.schema import MaxRecordingUniversalFilters, AssistantContextualTool
from .prompts import (
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    TOOL_USAGE_PROMPT,
    DATE_FIELDS_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# Create and register the FilterProfile for session recordings after the class is defined
# Format the prompt with all the required components
formatted_prompt = f"""
{PRODUCT_DESCRIPTION_PROMPT}

{SESSION_REPLAY_EXAMPLES_PROMPT}

{FILTER_FIELDS_TAXONOMY_PROMPT}

{DATE_FIELDS_PROMPT}

{TOOL_USAGE_PROMPT}

{HUMAN_IN_THE_LOOP_PROMPT}
""".strip()

SESSION_RECORDINGS_FILTER_PROFILE = FilterProfile(
    tool_name=AssistantContextualTool.SEARCH_SESSION_RECORDINGS.value,
    response_model=MaxRecordingUniversalFilters,
    formatted_prompt=formatted_prompt,
)

# Register the filter profile
register_filter_profile(SESSION_RECORDINGS_FILTER_PROFILE)


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

    async def _arun_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        graph = FilterOptionsGraph(team=self._team, user=self._user).compile_full_graph()

        graph_input = {
            "change": change,
            "generated_filter_options": None,
            "messages": [],
            "tool_progress_messages": [],
            "tool_name": SESSION_RECORDINGS_FILTER_PROFILE.tool_name,
            **self.context,
        }

        result = await graph.ainvoke(graph_input)

        if "generated_filter_options" not in result or result["generated_filter_options"] is None:
            last_message = result["intermediate_steps"][-1]
            help_content = "I need more information to proceed."

            tool_call_id = getattr(last_message, "tool", None)

            if tool_call_id == "ask_user_for_help" or tool_call_id == "max_iterations":
                content = getattr(last_message, "tool_input", None)
                help_content = str(content)

            current_filters = MaxRecordingUniversalFilters.model_validate(self.context.get("current_filters", {}))

            return help_content, current_filters

        try:
            result = MaxRecordingUniversalFilters.model_validate(result["generated_filter_options"]["data"])
        except Exception as e:
            raise ValueError(f"Failed to generate MaxRecordingUniversalFilters: {e}")

        return "✅ Updated session recordings filters.", result
