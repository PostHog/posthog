import time
import asyncio
from typing import Any, cast
from uuid import uuid4

import structlog
import posthoganalytics
from langchain_core.agents import AgentAction
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantToolCallMessage,
    MaxRecordingUniversalFilters,
    NotebookUpdateMessage,
    RecordingsQuery,
)

from posthog.models.team.team import check_is_feature_available_for_team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)

from products.enterprise.backend.hogai.graph.base import AssistantNode
from products.enterprise.backend.hogai.graph.session_summaries.prompts import GENERATE_FILTER_QUERY_PROMPT
from products.enterprise.backend.hogai.llm import MaxChatOpenAI
from products.enterprise.backend.hogai.session_summaries.constants import (
    GROUP_SUMMARIES_MIN_SESSIONS,
    MAX_SESSIONS_TO_SUMMARIZE,
    SESSION_SUMMARIES_SYNC_MODEL,
)
from products.enterprise.backend.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from products.enterprise.backend.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
)
from products.enterprise.backend.hogai.session_summaries.session_group.stringify import SessionGroupSummaryStringifier
from products.enterprise.backend.hogai.session_summaries.session_group.summarize_session_group import (
    find_sessions_timestamps,
)
from products.enterprise.backend.hogai.session_summaries.session_group.summary_notebooks import (
    SummaryNotebookIntermediateState,
    create_empty_notebook_for_summary,
    generate_notebook_content_from_summary,
    update_notebook_from_summary_content,
)
from products.enterprise.backend.hogai.session_summaries.utils import logging_session_ids
from products.enterprise.backend.hogai.utils.state import prepare_reasoning_progress_message
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import AssistantNodeName
from products.enterprise.backend.hogai.utils.types.composed import MaxNodeName
from products.notebooks.backend.models import Notebook


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.SESSION_SUMMARIZATION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_search = _SessionSearch(self)
        self._session_summarizer = _SessionSummarizer(self)

    async def _stream_progress(self, progress_message: str) -> None:
        """Push summarization progress as reasoning messages"""
        content = prepare_reasoning_progress_message(progress_message)
        if content:
            self.dispatcher.update(content)

    async def _stream_notebook_content(self, content: dict, state: AssistantState, partial: bool = True) -> None:
        """Stream TipTap content directly to a notebook if notebook_id is present in state."""
        # Check if we have a notebook_id in the state
        if not state.notebook_short_id:
            self.logger.exception("No notebook_short_id in state, skipping notebook update")
            return
        if partial:
            # Create a notebook update message; not providing id to count it as a partial message on FE
            notebook_message = NotebookUpdateMessage(notebook_id=state.notebook_short_id, content=content)
        else:
            # If not partial - means the final state of the notebook to show "Open the notebook" button in the UI
            notebook_message = NotebookUpdateMessage(
                notebook_id=state.notebook_short_id, content=content, id=str(uuid4())
            )
        # Stream the notebook update
        self.dispatcher.message(notebook_message)

    def _has_video_validation_feature_flag(self) -> bool | None:
        """
        Check if the user has the video validation for session summaries feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "max-session-summarization-video-validation",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        # Search for session ids with filters (current or generated)
        search_result = await self._session_search.search_sessions(state, conversation_id, start_time, config)
        try:
            # No sessions were found
            if not search_result:
                return PartialAssistantState(
                    messages=[
                        AssistantToolCallMessage(
                            content="No sessions were found.",
                            tool_call_id=state.root_tool_call_id or "unknown",
                            id=str(uuid4()),
                        ),
                    ],
                    session_summarization_query=None,
                    root_tool_call_id=None,
                )
            # The search failed or clarification is needed
            if isinstance(search_result, PartialAssistantState):
                return search_result
            # Summarize sessions
            summaries_content = await self._session_summarizer.summarize_sessions(
                session_ids=search_result, state=state
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=summaries_content,
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                session_summarization_query=None,
                root_tool_call_id=None,
                # Ensure to pass the notebook id to the next node
                notebook_short_id=state.notebook_short_id,
            )
        except Exception as err:
            self._log_failure("Session summarization failed", conversation_id, start_time, err)
            return self._create_error_response(self._base_error_instructions, state)

    def _create_error_response(self, message: str, state: AssistantState) -> PartialAssistantState:
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=message,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            ],
            session_summarization_query=None,
            root_tool_call_id=None,
            notebook_short_id=state.notebook_short_id,
        )

    def _log_failure(self, message: str, conversation_id: str, start_time: float, error: Any = None):
        self.logger.error(
            message,
            extra={
                "team_id": getattr(self._team, "id", "unknown"),
                "conversation_id": conversation_id,
                "execution_time_ms": round(time.time() - start_time, 2) * 1000,
                "error": str(error) if error else None,
            },
            exc_info=error if error else None,
        )

    @property
    def _base_error_instructions(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."


class _SessionSearch:
    """Handles the search to get session ids with filters (current or generated)"""

    def __init__(self, node: SessionSummarizationNode):
        self._node = node

    async def _generate_replay_filters(
        self, state: AssistantState, config: RunnableConfig, filter_query: str, conversation_id: str, start_time: float
    ) -> MaxRecordingUniversalFilters | str | None:
        """
        Generates replay filters to get session ids by directly using SearchSessionRecordingsTool.

        Returns:
            - filters: MaxRecordingUniversalFilters if successful
            - question: str if clarification is needed
            - None if there's an error
        """
        from products.replay.backend.max_tools import SearchSessionRecordingsTool  # Avoid circular import

        # Create the tool instance with minimal context (no current_filters for fresh generation)
        tool = await SearchSessionRecordingsTool.create_tool_class(
            team=self._node._team,
            user=self._node._user,
            node_path=self._node.node_path,
            state=state,
            config=config,
            context_manager=self._node.context_manager,
        )
        try:
            # Call the tool's graph directly to use the same implementation as in the tool (avoid duplication)
            result = await tool._invoke_graph(change=filter_query)
            if not result.get("output"):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool returned no output for session summarization (query: {filter_query})",
                    conversation_id,
                    start_time,
                )
                return None
            output = result["output"]
            # Return filters if generated successfully
            if isinstance(output, MaxRecordingUniversalFilters):
                return output
            # Return clarification question if needed
            if not result.get("intermediate_steps") or not len(result["intermediate_steps"][-1]):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool returned no intermediate steps for session summarization (query: {filter_query}): {result}",
                    conversation_id,
                    start_time,
                )
                return None
            last_step = result["intermediate_steps"][-1][0]
            if (
                not isinstance(last_step, AgentAction)
                or last_step.tool != "ask_user_for_help"
                or not isinstance(last_step.tool_input, str)
            ):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool last step was neither filters nor ask_user_for_help "
                    f"for session summarization (query: {filter_query}): {result}",
                    conversation_id,
                    start_time,
                )
                return None
            return last_step.tool_input
        except Exception as e:
            self._node.logger.exception(
                f"Unexpected error generating replay filters for session summarization: {e}",
                extra={
                    "team_id": getattr(self._node._team, "id", "unknown"),
                    "user_id": getattr(self._node._user, "id", "unknown"),
                    "query": filter_query,
                },
            )
            return None

    def _convert_max_filters_to_recordings_query(self, replay_filters: MaxRecordingUniversalFilters) -> RecordingsQuery:
        """Convert Max-generated filters into recordings query format"""
        properties = []
        if replay_filters.filter_group and replay_filters.filter_group.values:
            for inner_group in replay_filters.filter_group.values:
                if hasattr(inner_group, "values"):
                    properties.extend(inner_group.values)
        recordings_query = RecordingsQuery(
            date_from=replay_filters.date_from,
            date_to=replay_filters.date_to,
            properties=properties,
            filter_test_accounts=replay_filters.filter_test_accounts,
            order=replay_filters.order,
            # Handle duration filters - preserve the original key (e.g., "active_seconds" or "duration")
            having_predicates=(
                [
                    {"key": dur.key, "type": "recording", "operator": dur.operator, "value": dur.value}
                    for dur in (replay_filters.duration or [])
                ]
                if replay_filters.duration
                else None
            ),
        )
        return recordings_query

    def _convert_current_filters_to_recordings_query(self, current_filters: dict[str, Any]) -> RecordingsQuery:
        """Convert current filters into recordings query format"""
        from products.enterprise.backend.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
            convert_filters_to_recordings_query,
        )

        # Create a temporary playlist object to use the conversion function
        temp_playlist = SessionRecordingPlaylist(filters=current_filters)
        recordings_query = convert_filters_to_recordings_query(temp_playlist)
        return recordings_query

    def _get_session_ids_with_filters(self, replay_filters: RecordingsQuery, limit: int) -> list[str] | None:
        """Get session ids from DB with filters"""
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        # Execute the query to get session IDs
        replay_filters.limit = limit
        try:
            query_runner = SessionRecordingListFromQuery(
                team=self._node._team, query=replay_filters, hogql_query_modifiers=None, limit=limit
            )
            results = query_runner.run()
        except Exception as e:
            self._node.logger.exception(
                f"Error getting session ids for session summarization with filters query "
                f"({replay_filters.model_dump_json(exclude_none=True)}): {e}"
            )
            return None
        # Extract session IDs
        session_ids = [recording["session_id"] for recording in results.results]
        return session_ids if session_ids else None

    async def _generate_filter_query(self, plain_text_query: str, config: RunnableConfig) -> str:
        """Generate a filter query for the user's summarization query to keep the search context clear"""
        messages = [
            ("human", GENERATE_FILTER_QUERY_PROMPT.format(input_query=plain_text_query)),
        ]
        prompt = ChatPromptTemplate.from_messages(messages)
        model = MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._node._user, team=self._node._team
        )
        chain = prompt | model | StrOutputParser()
        filter_query = chain.invoke({}, config=config)
        # Validate the generated filter query is not empty or just whitespace
        if not filter_query or not filter_query.strip():
            raise ValueError(
                f"Filter query generated for session summarization is empty or just whitespace (initial query: {plain_text_query})"
            )
        return filter_query

    async def search_sessions(
        self, state: AssistantState, conversation_id: str, start_time: float, config: RunnableConfig
    ) -> list[str] | PartialAssistantState | None:
        # If query was not provided for some reason
        if state.session_summarization_query is None:
            self._node._log_failure(
                f"Session summarization query is not provided when summarizing sessions: {state.session_summarization_query}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)
        # If the decision on the current filters is not made
        if state.should_use_current_filters is None:
            self._node._log_failure(
                f"Use current filters decision is not made when summarizing sessions: {state.should_use_current_filters}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)
        # If the current filters were marked as relevant, but not present in the context
        current_filters = (
            self._node.context_manager.get_contextual_tools()
            .get("search_session_recordings", {})
            .get("current_filters")
        )
        try:
            # Use current filters, if provided
            if state.should_use_current_filters:
                if not current_filters:
                    self._node._log_failure(
                        f"Use current filters decision was set to True, but current filters were not provided when summarizing sessions: {state.should_use_current_filters}",
                        conversation_id,
                        start_time,
                    )
                    return self._node._create_error_response(self._node._base_error_instructions, state)
                current_filters = cast(dict[str, Any], current_filters)
                replay_filters = self._convert_current_filters_to_recordings_query(current_filters)
            # If not - generate filters to get session ids from DB
            else:
                filter_query = await self._generate_filter_query(state.session_summarization_query, config)
                filter_generation_result = await self._generate_replay_filters(
                    state=state,
                    config=config,
                    filter_query=filter_query,
                    conversation_id=conversation_id,
                    start_time=start_time,
                )
                if filter_generation_result is None:
                    return self._node._create_error_response(
                        "INSTRUCTIONS: Tell the user that you encountered an issue while generating session filters to match the user's query. "
                        'Suggest to use more specific conditions (like ids) or go to "Session replay" page and use its filters when summarizing.',
                        state,
                    )
                # Check if we got a clarification question instead of filters
                if isinstance(filter_generation_result, str):
                    # Return the clarification question to the user
                    return PartialAssistantState(
                        messages=[
                            AssistantToolCallMessage(
                                content=filter_generation_result,
                                tool_call_id=state.root_tool_call_id or "unknown",
                                id=str(uuid4()),
                            ),
                        ],
                        session_summarization_query=None,
                        root_tool_call_id=None,
                    )
                # Use filters when generated successfully
                replay_filters = self._convert_max_filters_to_recordings_query(filter_generation_result)
            # Query the filters to get session ids
            query_limit = state.session_summarization_limit
            if not query_limit or query_limit <= 0 or query_limit > MAX_SESSIONS_TO_SUMMARIZE:
                # If no limit provided (none or negative) or too large - use the default limit
                query_limit = MAX_SESSIONS_TO_SUMMARIZE
            session_ids = await database_sync_to_async(self._get_session_ids_with_filters, thread_sensitive=False)(
                replay_filters, query_limit
            )
            return session_ids
        except Exception as e:
            self._node._log_failure(
                f"Unexpected error when searching sessions for session summarization: {e}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)


class _SessionSummarizer:
    """Handles the summarization of session recordings"""

    def __init__(self, node: SessionSummarizationNode):
        self._node = node
        self._intermediate_state: SummaryNotebookIntermediateState | None = None

    async def _summarize_sessions_individually(self, session_ids: list[str]) -> str:
        """Summarize sessions individually with progress updates."""
        total = len(session_ids)
        completed = 0
        video_validation_enabled = self._node._has_video_validation_feature_flag()

        async def _summarize(session_id: str) -> dict[str, Any]:
            nonlocal completed
            result = await execute_summarize_session(
                session_id=session_id,
                user_id=self._node._user.id,
                team=self._node._team,
                model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
                video_validation_enabled=video_validation_enabled,
            )
            completed += 1
            # Update the user on the progress
            await self._node._stream_progress(progress_message=f"Watching sessions ({completed}/{total})")
            return result

        # Run all tasks concurrently
        tasks = [_summarize(sid) for sid in session_ids]
        summaries = await asyncio.gather(*tasks)
        await self._node._stream_progress(progress_message=f"Generating a summary, almost there")
        # Stringify, as chat doesn't need full JSON to be context-aware, while providing it could overload the context
        stringified_summaries = []
        for summary in summaries:
            stringifier = SingleSessionSummaryStringifier(summary)
            stringified_summaries.append(stringifier.stringify_session())
        # Combine all stringified summaries into a single string
        summaries_str = "\n\n".join(stringified_summaries)
        return summaries_str

    async def _summarize_sessions_as_group(
        self,
        session_ids: list[str],
        state: AssistantState,
        summary_title: str | None,
        notebook: Notebook | None,
    ) -> str:
        """Summarize sessions as a group (for larger sets)."""
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self._node._team)
        # Check if the summaries should be validated with videos
        video_validation_enabled = self._node._has_video_validation_feature_flag()
        # Initialize intermediate state with plan
        self._intermediate_state = SummaryNotebookIntermediateState(
            team_name=self._node._team.name, summary_title=summary_title
        )
        # Stream initial plan
        initial_state = self._intermediate_state.format_intermediate_state()
        await self._node._stream_notebook_content(initial_state, state)

        async for update_type, step, data in execute_summarize_session_group(
            session_ids=session_ids,
            user_id=self._node._user.id,
            team=self._node._team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            extra_summary_context=None,
            video_validation_enabled=video_validation_enabled,
        ):
            # Max "reasoning" text update message
            if update_type == SessionSummaryStreamUpdate.UI_STATUS:
                if not isinstance(data, str):
                    raise TypeError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.UI_STATUS}: {type(data)} "
                        f"(expected: str)"
                    )
                # Update intermediate state based on step enum (no content, as it's just a status message)
                self._intermediate_state.update_step_progress(content=None, step=step)
                # Status message - stream to user
                await self._node._stream_progress(progress_message=data)
            # Notebook intermediate data update messages
            elif update_type == SessionSummaryStreamUpdate.NOTEBOOK_UPDATE:
                if not isinstance(data, dict):
                    raise TypeError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.NOTEBOOK_UPDATE}: {type(data)} "
                        f"(expected: dict)"
                    )
                # Update intermediate state based on step enum
                self._intermediate_state.update_step_progress(content=data, step=step)
                # Stream the updated intermediate state
                formatted_state = self._intermediate_state.format_intermediate_state()
                await self._node._stream_notebook_content(formatted_state, state)
            # Final summary result
            elif update_type == SessionSummaryStreamUpdate.FINAL_RESULT:
                if not isinstance(data, EnrichedSessionGroupSummaryPatternsList):
                    raise ValueError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(data)} "
                        f"(expected: EnrichedSessionGroupSummaryPatternsList)"
                    )
                # Replace the intermediate state with final report
                summary = data
                tasks_available = await database_sync_to_async(
                    check_is_feature_available_for_team, thread_sensitive=False
                )(self._node._team.id, "TASK_SUMMARIES")
                summary_content = generate_notebook_content_from_summary(
                    summary=summary,
                    session_ids=session_ids,
                    project_name=self._node._team.name,
                    team_id=self._node._team.id,
                    tasks_available=tasks_available,
                    summary_title=summary_title,
                )
                await self._node._stream_notebook_content(summary_content, state, partial=False)
                # Update the notebook through BE for cases where the chat was closed
                await update_notebook_from_summary_content(
                    notebook=notebook, summary_content=summary_content, session_ids=session_ids
                )
                # Stringify the summary to "weight" less and apply example limits per pattern, so it won't overload the context
                stringifier = SessionGroupSummaryStringifier(summary.model_dump(exclude_none=False))
                summary_str = stringifier.stringify_patterns()
                return summary_str
            else:
                raise ValueError(
                    f"Unexpected update type ({update_type}) in session group summarization (session_ids: {logging_session_ids(session_ids)})."
                )
        else:
            raise ValueError(
                f"No summary was generated from session group summarization (session_ids: {logging_session_ids(session_ids)})"
            )

    async def summarize_sessions(
        self,
        session_ids: list[str],
        state: AssistantState,
    ) -> str:
        # Process sessions based on count
        base_message = f"Found sessions ({len(session_ids)})"
        if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS:
            # If small amount of sessions - there are no patterns to extract, so summarize them individually and return as is
            await self._node._stream_progress(
                progress_message=f"{base_message}. We will do a quick summary, as the scope is small",
            )
            summaries_content = await self._summarize_sessions_individually(session_ids=session_ids)
            return summaries_content
        # Check if the notebook is provided, create a notebook to fill if not
        notebook = None
        if not state.notebook_short_id:
            notebook = await create_empty_notebook_for_summary(
                user=self._node._user, team=self._node._team, summary_title=state.summary_title
            )
            # Could be moved to a separate "create notebook" node (or reuse the one from deep research)
            state.notebook_short_id = notebook.short_id
        # For large groups, process in detail, searching for patterns
        # TODO: Allow users to define the pattern themselves (or rather catch it from the query)
        await self._node._stream_progress(
            progress_message=f"{base_message}. We will analyze in detail, and store the report in a notebook",
        )
        summaries_content = await self._summarize_sessions_as_group(
            session_ids=session_ids,
            state=state,
            summary_title=state.summary_title,
            notebook=notebook,
        )
        return summaries_content
