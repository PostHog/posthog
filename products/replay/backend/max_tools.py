from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from typing import Any
from posthog.schema import MaxRecordingUniversalFilters
from langgraph.config import get_stream_writer
from ee.hogai.utils.types import AssistantState
from collections.abc import AsyncIterator

# Import the prompts you want to pass to the graph
from .prompts import (
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
)


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
    thinking_message: str = "Coming up with session recordings filters..."
    root_system_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    async def _arun_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `search_session_recordings` tool")

        if not self._team or not self._user:
            raise ValueError("Team and User are required for the `search_session_recordings` tool")

        # Create graph with injected prompts
        injected_prompts = {
            "product_description_prompt": PRODUCT_DESCRIPTION_PROMPT,
            "response_formats_prompt": SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
            "examples_prompt": SESSION_REPLAY_EXAMPLES_PROMPT,
        }

        graph = FilterOptionsGraph(
            team=self._team, user=self._user, injected_prompts=injected_prompts
        ).compile_full_graph()

        graph_input = {
            "change": change,
            "generated_filter_options": None,
            "messages": [],
            **self.context,
        }

        writer = get_stream_writer()

        generator: AsyncIterator[Any] = graph.astream(
            graph_input, config=self._config, stream_mode=["messages", "values", "updates", "debug"], subgraphs=True
        )

        async for chunk in generator:
            writer(chunk)

        snapshot = await graph.aget_state(self._config)

        # Get the final state after streaming
        state = AssistantState.model_validate(snapshot.values)

        # Check if this is a help request (filter_options_dict is None but has messages)
        if not state.generated_filter_options and state.messages:
            last_message = state.messages[-1]
            help_content = "I need more information to proceed."
            tool_call_id = getattr(last_message, "tool_call_id", None)
            content = getattr(last_message, "content", None)
            if tool_call_id == "ask_user_for_help":
                help_content = str(content)

            current_filters = MaxRecordingUniversalFilters.model_validate(self.context.get("current_filters", {}))

            return help_content, current_filters

        # Convert to the expected type
        if not state.generated_filter_options:
            raise ValueError("No filter options were generated.")

        try:
            result = MaxRecordingUniversalFilters.model_validate(state.generated_filter_options["data"])
        except Exception as e:
            raise ValueError(f"Failed to convert filter options to MaxRecordingUniversalFilters: {e}")

        return "✅ Updated session recordings filters.", result
