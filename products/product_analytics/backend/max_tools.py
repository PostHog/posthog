import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from ee.hogai.graph.root.tools import CreateInsightTool
from ee.hogai.utils.types.base import InsightArtifact, ToolResult

logger = structlog.get_logger(__name__)


class EditCurrentInsightArgs(BaseModel):
    """
    Edits the insight visualization the user is currently working on, by creating a query or iterating on a previous query.
    """

    query_description: str = Field(
        description="The new query to edit the current insight. Must include all details from the current insight plus any change on top of them. Include any relevant information from the current conversation, as the tool does not have access to the conversation."
    )


class EditCurrentInsightTool(CreateInsightTool):
    name: str = AssistantTool.EDIT_CURRENT_INSIGHT.value
    description: str = (
        "Update the insight the user is currently working on, based on the current insight's JSON schema."
    )
    system_prompt_template: str = """The user is currently editing an insight (aka query). Here is that insight's current definition:

```json
{current_query}
```

IMPORTANT: This tool substitutes the `create_and_query_insight` tool.
IMPORTANT: DO NOT REMOVE ANY FIELDS FROM THE CURRENT INSIGHT DEFINITION. DO NOT CHANGE ANY OTHER FIELDS THAN THE ONES THE USER ASKED FOR. KEEP THE REST AS IS.
""".strip()

    args_schema: type[BaseModel] = EditCurrentInsightArgs

    async def _arun_impl(self, query_description: str) -> ToolResult:
        result = await super()._arun_impl(query_description)
        if len(result.artifacts) > 0 and isinstance(result.artifacts[0], InsightArtifact) and result.artifacts[0].query:
            return await self._successful_execution(result.content, metadata={"query": result.artifacts[0].query})
        else:
            return await self._failed_execution()
