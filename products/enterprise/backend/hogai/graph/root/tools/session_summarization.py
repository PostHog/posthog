from typing import Literal

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from products.enterprise.backend.hogai.graph.session_summaries.nodes import SessionSummarizationNode
from products.enterprise.backend.hogai.tool import MaxTool, ToolMessagesArtifact
from products.enterprise.backend.hogai.utils.types.base import AssistantState, PartialAssistantState

SESSION_SUMMARIZATION_TOOL_PROMPT = """
Use this tool to summarize session recordings by analysing the events within those sessions to find patterns and issues.
It will return a textual summary of the captured session recordings.

# When to use the tool:
When the user asks to summarize session recordings:
- "summarize" synonyms: "watch", "analyze", "review", and similar
- "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar

# When NOT to use the tool:
- When the user asks to find, search for, or look up session recordings, but doesn't ask to summarize them
- When users asks to update, change, or adjust session recordings filters

# Synonyms
- "summarize": "watch", "analyze", "review", and similar
- "session recordings": "sessions", "recordings", "replays", "user sessions", and similar

# Managing context
If the conversation history contains context about the current filters or session recordings, follow these steps:
- Convert the user query into a `session_summarization_query`
- The query should be used to understand the user's intent
- Decide if the query is relevant to the current filters and set `should_use_current_filters` accordingly
- Generate the `summary_title` based on the user's query and the current filters
- Extract the `session_summarization_limit` from the user's query if present

Otherwise:
- Convert the user query into a `session_summarization_query`
- The query should be used to search for relevant sessions and then summarize them
- Assume the `should_use_current_filters` should be always `false`
- Generate the `summary_title` based on the user's query
- Extract the `session_summarization_limit` from the user's query if present

# Additional guidelines
- CRITICAL: Always pass the user's complete, unmodified query to the `session_summarization_query` parameter
- DO NOT truncate, summarize, or extract keywords from the user's query
- The query is used to find relevant sessions - context helps find better matches
- Use explicit tool definition to make a decision
""".strip()


class SessionSummarizationToolArgs(BaseModel):
    session_summarization_query: str = Field(
        description="""
        - The user's complete query for session recordings summarization.
        - This will be used to find relevant session recordings.
        - Always pass the user's complete, unmodified query.
        - Examples:
          * 'summarize all session recordings from yesterday'
          * 'analyze mobile user session recordings from last week, even if 1 second'
          * 'watch last 300 session recordings of MacOS users from US'
          * and similar
        """
    )
    should_use_current_filters: bool = Field(
        description="""
        - Whether to use current filters from user's UI to find relevant session recordings.
        - IMPORTANT: Should be always `false` if the current filters or `search_session_recordings` tool are not present in the conversation history.
        - Examples:
          * Set to `true` if one of the conditions is met:
            - the user wants to summarize "current/selected/opened/my/all/these" session recordings
            - the user wants to use "current/these" filters
            - the user's query specifies filters identical to the current filters
            - if the user's query doesn't specify any filters/conditions
            - the user refers to what they're "looking at" or "viewing"
          * Set to `false` if one of the conditions is met:
            - no current filters or `search_session_recordings` tool are present in the conversation
            - the user specifies date/time period different from the current filters
            - the user specifies conditions (user, device, id, URL, etc.) not present in the current filters
        """,
    )
    summary_title: str = Field(
        description="""
        - The name of the summary that is expected to be generated from the user's `session_summarization_query` and/or `current_filters` (if present).
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
          * If `should_use_current_filters` is `false`, then the `summary_title` should be generated based on the `session_summarization_query`:
            - query: "I want to watch all the sessions of user `user@example.com` in the last 30 days no matter how long" -> name: "Sessions of the user user@example.com (last 30 days)"
            - query: "summarize my last 100 session recordings" -> name: "Last 100 sessions"
            - and similar
          * If `should_use_current_filters` is `true`, then the `summary_title` should be generated based on the current filters in the context (if present):
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
          * If there's not enough context to generated the summary name - keep it an empty string ("")
        """
    )
    session_summarization_limit: int = Field(
        description="""
        - The maximum number of sessions to summarize
        - This will be used to apply to DB query to limit the results.
        - Extract the limit from the user's query if present. Set to -1 if not present.
        - IMPORTANT: Extract the limit only if the user's query explicitly mentions a number of sessions to summarize.
        - Examples:
          * 'summarize all sessions from yesterday' -> limit: -1
          * 'summarize last 100 sessions' -> limit: 100
          * 'summarize these sessions' -> limit: -1
          * 'summarize first 10 of these sessions' -> limit: 10
          * 'summarize the sessions of the users with at least 10 events' -> limit: -1
          * 'summarize the sessions of the last 30 days' -> limit: -1
          * 'summarize last 500 sessions of the MacOS users from US' -> limit: 500
          * and similar
        """
    )


class SessionSummarizationTool(MaxTool):
    name: Literal["session_summarization"] = "session_summarization"
    description: str = SESSION_SUMMARIZATION_TOOL_PROMPT
    thinking_message: str = "Summarizing session recordings"
    context_prompt_template: str = "Summarizes session recordings based on the user's query and current filters"
    args_schema: type[BaseModel] = SessionSummarizationToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(
        self,
        session_summarization_query: str,
        should_use_current_filters: bool,
        summary_title: str,
        session_summarization_limit: int,
    ) -> tuple[str, ToolMessagesArtifact | None]:
        node = SessionSummarizationNode(self._team, self._user)
        chain: RunnableLambda[AssistantState, PartialAssistantState | None] = RunnableLambda(node)
        copied_state = self._state.model_copy(
            deep=True,
            update={
                "root_tool_call_id": self.tool_call_id,
                "session_summarization_query": session_summarization_query,
                "should_use_current_filters": should_use_current_filters,
                "summary_title": summary_title,
                "session_summarization_limit": session_summarization_limit,
            },
        )
        result = await chain.ainvoke(copied_state)
        if not result or not result.messages:
            return "Session summarization failed", None
        return "", ToolMessagesArtifact(messages=result.messages)
