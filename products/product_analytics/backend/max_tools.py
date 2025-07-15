from typing import Any
from collections.abc import AsyncIterator

from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantState
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    VisualizationMessage,
)

QueryResult = AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery


class EditCurrentInsightArgs(BaseModel):
    """
    Edits the insight visualization the user is currently working on, by creating a query or iterating on a previous query.
    """

    query_description: str = Field(
        description="The new query to edit the current insight. Must include all details from the current insight plus any change on top of them. Include any relevant information from the current conversation, as the tool does not have access to the conversation."
    )
    query_kind: str = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


class EditCurrentInsightTool(MaxTool):
    name: str = "create_and_query_insight"  # this is the same name as the "insights" tool in the backend, as this overwrites that tool's functionality to be able to send the result to the frontend
    description: str = (
        "Update the insight the user is currently working on, based on the current insight's JSON schema."
    )
    thinking_message: str = "Editing your insight"
    root_system_prompt_template: str = "The user is currently editing an insight (aka query). Here is that insight's current definition, which can be edited using the `create_and_query_insight` tool:\n```json\n{current_query}\n```"
    args_schema: type[BaseModel] = EditCurrentInsightArgs

    async def _arun_impl(self, query_kind: str, query_description: str) -> tuple[str, None]:
        from ee.hogai.graph.graph import InsightsAssistantGraph  # avoid circular import

        if "current_query" not in self.context:
            raise ValueError("Context `current_query` is required for the `create_and_query_insight` tool")

        graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()
        state = self._state
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an AssistantMessage")
        if last_message.tool_calls is None or len(last_message.tool_calls) == 0:
            raise ValueError("Last message has no tool calls")

        state.root_tool_insight_plan = query_description
        state.root_tool_insight_type = query_kind
        state.root_tool_call_id = last_message.tool_calls[0].id

        writer = get_stream_writer()
        generator: AsyncIterator[Any] = graph.astream(
            state, config=self._config, stream_mode=["messages", "values", "updates", "debug"], subgraphs=True
        )
        async for chunk in generator:
            writer(chunk)

        snapshot = await graph.aget_state(self._config)
        state = AssistantState.model_validate(snapshot.values)
        last_message = state.messages[-1]
        viz_messages = [message for message in state.messages if isinstance(message, VisualizationMessage)][-1:]
        if not viz_messages:
            # The agent has requested help from the user
            self._state = state
            return "", None

        result = viz_messages[0].answer

        if not isinstance(last_message, AssistantToolCallMessage):
            raise ValueError("Last message is not an AssistantToolCallMessage")
        last_message.ui_payload = {"create_and_query_insight": result}
        # we hide the tool call message from the frontend, as it's not a user facing message
        last_message.visible = False

        await graph.aupdate_state(self._config, values={"messages": [last_message]})
        new_state = await graph.aget_state(self._config)
        state = AssistantState.model_validate(new_state.values)
        self._state = state

        # We don't want to return anything, as we're using the tool to update the state
        return "", None
