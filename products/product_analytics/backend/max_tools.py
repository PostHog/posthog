from collections.abc import AsyncIterator
from typing import Any

from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantToolCallMessage, VisualizationMessage

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantState

QUERY_KIND_DESCRIPTION_PROMPT = """
## Trends
A trends insight visualizes events over time using time series. They're useful for finding patterns in historical data.

The trends insights have the following features:
- The insight can show multiple trends in one request.
- Custom formulas can calculate derived metrics, like `A/B*100` to calculate a ratio.
- Filter and break down data using multiple properties.
- Compare with the previous period and sample data.
- Apply various aggregation types, like sum, average, etc., and chart types.
- And more.

Examples of use cases include:
- How the product's most important metrics change over time.
- Long-term patterns, or cycles in product's usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- Users can also visualize the same data points in a variety of ways.

## Funnel
A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels use two or more series, so the conversation history should mention at least two events.

The funnel insights have the following features:
- Various visualization types (steps, time-to-convert, historical trends).
- Filter data and apply exclusion steps.
- Break down data using a single property.
- Specify conversion windows, details of conversion calculation, attribution settings.
- Sample data.
- And more.

Examples of use cases include:
- Conversion rates.
- Drop off steps.
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
- Average/median time to convert.
- Conversion trends over time.

## Retention
A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

The retention insights have the following features: filter data, sample data, and more.

Examples of use cases include:
- How many users come back and perform an action after their first visit.
- How many users come back to perform action X after performing action Y.
- How often users return to use a specific feature.

## SQL
The 'sql' insight type allows you to write arbitrary SQL queries to retrieve data.

The SQL insights have the following features:
- Filter data using arbitrary SQL.
- All ClickHouse SQL features.
- You can nest subqueries as needed.
""".strip()


class EditCurrentInsightArgs(BaseModel):
    """
    Edits the insight visualization the user is currently working on, by creating a query or iterating on a previous query.
    """

    query_description: str = Field(
        description="The new query to edit the current insight. Must include all details from the current insight plus any change on top of them. Include any relevant information from the current conversation, as the tool does not have access to the conversation."
    )
    query_kind: str = Field(description=QUERY_KIND_DESCRIPTION_PROMPT)


class EditCurrentInsightTool(MaxTool):
    name: str = "create_and_query_insight"  # this is the same name as the "insights" tool in the backend, as this overwrites that tool's functionality to be able to send the result to the frontend
    description: str = (
        "Update the insight the user is currently working on, based on the current insight's JSON schema."
    )
    thinking_message: str = "Editing your insight"
    root_system_prompt_template: str = """The user is currently editing an insight (aka query). Here is that insight's current definition, which can be edited using the `create_and_query_insight` tool:

```json
{current_query}
```

IMPORTANT: DO NOT REMOVE ANY FIELDS FROM THE CURRENT INSIGHT DEFINITION. DO NOT CHANGE ANY OTHER FIELDS THAN THE ONES THE USER ASKED FOR. KEEP THE REST AS IS.
""".strip()

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
