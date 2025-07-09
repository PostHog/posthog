from pydantic import BaseModel, Field
from collections.abc import Iterator

from ee.hogai.tool import MaxTool
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from typing import Any
from posthog.schema import MaxRecordingUniversalFilters
from langgraph.config import get_stream_writer
from ee.hogai.utils.types import AssistantState


class SearchSessionRecordingsArgs(BaseModel):
    change: str = Field(description="The specific change to be made to recordings filters, briefly described.")


class SearchSessionRecordingsTool(MaxTool):
    name: str = "search_session_recordings"
    description: str = (
        "Update session recordings filters on this page, in order to search for session recordings by any criteria."
    )
    thinking_message: str = "Coming up with session recordings filters..."
    root_system_prompt_template: str = "Current recordings filters are: {current_filters}"
    args_schema: type[BaseModel] = SearchSessionRecordingsArgs

    def _run_impl(self, change: str) -> tuple[str, MaxRecordingUniversalFilters]:
        if "current_filters" not in self.context:
            raise ValueError("Context `current_filters` is required for the `search_session_recordings` tool")

        if not self._team or not self._user:
            raise ValueError("Team and User are required for the `search_session_recordings` tool")

        graph = FilterOptionsGraph(team=self._team, user=self._user).compile_full_graph()

        graph_input = {
            "change": change,
            "generated_filter_options": None,
            "messages": [],
            # "root_tool_call_id": "",
            **self.context,
        }

        writer = get_stream_writer()

        generator: Iterator[Any] = graph.stream(
            graph_input, config=self._config, stream_mode=["messages", "values", "updates", "debug"], subgraphs=True
        )

        for chunk in generator:
            writer(chunk)

        # Get the final state after streaming
        state = AssistantState.model_validate(graph.get_state(self._config).values)

        # Check if this is a help request (filter_options_dict is None but has messages)
        if not state.generated_filter_options and state.messages:
            messages = state.messages
            help_content = "I need more information to proceed."

            for message in messages:
                # Only check content for message types that have it
                content = getattr(message, "content", None)
                if content:
                    help_content = str(content)
                    break

            current_filters = MaxRecordingUniversalFilters.model_validate(self.context.get("current_filters", {}))
            self._state = state
            return help_content, current_filters

        # Convert to the expected type
        if not state.generated_filter_options:
            raise ValueError("No filter options were generated.")

        try:
            result = MaxRecordingUniversalFilters.model_validate(state.generated_filter_options["data"])
        except Exception as e:
            raise ValueError(f"Failed to convert filter options to MaxRecordingUniversalFilters: {e}")

        return "✅ Updated session recordings filters.", result
