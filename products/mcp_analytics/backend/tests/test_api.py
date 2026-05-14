import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models.utils import uuid7

from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPSession


class TestMCPAnalyticsFacade(APIBaseTest):
    def test_create_feedback_submission(self) -> None:
        submission = api.create_feedback_submission(
            self.team,
            self.user,
            contracts.CreateFeedbackSubmission(
                goal="understand MCP usage",
                feedback="Need clearer explanations for query failures",
                category=MCPAnalyticsSubmission.FeedbackCategory.RESULTS,
                context=contracts.SubmissionContext(
                    attempted_tool="query_run",
                    mcp_client_name="Claude Desktop",
                    mcp_client_version="1.0.0",
                    mcp_protocol_version="2025-03-26",
                    mcp_transport="streamable_http",
                    mcp_session_id="session-123",
                    mcp_trace_id="trace-456",
                ),
            ),
        )

        assert submission.kind == enums.SubmissionKind.FEEDBACK
        assert submission.goal == "understand MCP usage"
        assert submission.summary == "Need clearer explanations for query failures"
        assert submission.category == MCPAnalyticsSubmission.FeedbackCategory.RESULTS
        assert submission.attempted_tool == "query_run"
        assert submission.mcp_client_name == "Claude Desktop"
        assert submission.mcp_client_version == "1.0.0"
        assert submission.mcp_protocol_version == "2025-03-26"
        assert submission.mcp_transport == "streamable_http"
        assert submission.mcp_session_id == "session-123"
        assert submission.mcp_trace_id == "trace-456"

    def test_list_missing_capability_submissions(self) -> None:
        api.create_missing_capability_submission(
            self.team,
            self.user,
            contracts.CreateMissingCapabilitySubmission(
                goal="debug a survey",
                missing_capability="Need a survey eligibility explainer",
                blocked=True,
            ),
        )

        submissions = api.list_missing_capability_submissions(self.team)

        assert len(submissions) == 1
        assert submissions[0].kind == enums.SubmissionKind.MISSING_CAPABILITY


class TestListMCPSessions(APIBaseTest):
    def _create_session(
        self,
        session_id: str,
        tools_used: list[str],
        client_name: str = "Claude Desktop",
        session_start: datetime | None = None,
        session_end: datetime | None = None,
    ) -> MCPSession:
        session_start = session_start or datetime.now(tz=UTC) - timedelta(minutes=5)
        session_end = session_end or datetime.now(tz=UTC)
        return MCPSession.objects.create(
            team=self.team,
            session_id=session_id,
            session_start=session_start,
            session_end=session_end,
            duration_seconds=int((session_end - session_start).total_seconds()),
            tools_used=tools_used,
            mcp_client_name=client_name,
        )

    def test_lists_sessions_in_newest_first_order(self) -> None:
        session_a = str(uuid7())
        session_b = str(uuid7())
        now = datetime.now(tz=UTC)

        self._create_session(
            session_a,
            tools_used=["query_run", "insight_get"],
            session_start=now - timedelta(minutes=10),
            session_end=now - timedelta(minutes=8),
        )
        self._create_session(
            session_b,
            tools_used=["dashboard_get", "query_run"],
            client_name="Cursor",
            session_start=now - timedelta(minutes=5),
            session_end=now - timedelta(minutes=4),
        )

        sessions = api.list_mcp_sessions(self.team, limit=50, offset=0)

        assert len(sessions) == 2
        # Newest session_end first
        assert sessions[0].session_id == session_b
        assert sessions[0].mcp_client_name == "Cursor"
        assert sorted(sessions[0].tools_used) == ["dashboard_get", "query_run"]
        # tool_calls reflects the persisted total from the backfill activity
        assert sessions[0].tool_calls == 0

        assert sessions[1].session_id == session_a
        assert sessions[1].mcp_client_name == "Claude Desktop"
        assert sorted(sessions[1].tools_used) == ["insight_get", "query_run"]
        assert sessions[1].tool_calls == 0

    def test_returns_empty_list_when_no_sessions(self) -> None:
        assert api.list_mcp_sessions(self.team, limit=50, offset=0) == []


class TestListMCPToolCalls(ClickhouseTestMixin, APIBaseTest):
    def _capture_mcp_tool_call(
        self,
        session_id: str,
        tool_name: str = "query_run",
        timestamp: datetime | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="mcp_tool_call",
            distinct_id=f"user_{uuid.uuid4().hex[:8]}",
            properties={"$session_id": session_id, "$mcp_tool_name": tool_name},
            timestamp=timestamp or datetime.now(tz=UTC),
            event_uuid=uuid.uuid4(),
        )

    def test_excludes_events_older_than_default_lookback(self) -> None:
        # Same 30-day default lookback as the sessions list — anything older must be
        # excluded so a single session-detail page-view can't full-scan `events`.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._capture_mcp_tool_call(session_id, "recent", timestamp=now - timedelta(hours=1))
        self._capture_mcp_tool_call(session_id, "ancient", timestamp=now - timedelta(days=45))
        flush_persons_and_events()

        result = api.list_mcp_tool_calls(self.team, session_id=session_id)

        assert [tc.tool_name for tc in result.tool_calls] == ["recent"]
        assert result.truncated is False

    def test_explicit_date_range_narrows_window(self) -> None:
        # When the caller passes a date_from / date_to (e.g. the parent session's
        # first_seen / last_seen), only events inside the window come back.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._capture_mcp_tool_call(session_id, "before", timestamp=now - timedelta(hours=5))
        self._capture_mcp_tool_call(session_id, "inside", timestamp=now - timedelta(hours=2))
        self._capture_mcp_tool_call(session_id, "after", timestamp=now - timedelta(minutes=10))
        flush_persons_and_events()

        result = api.list_mcp_tool_calls(
            self.team,
            session_id=session_id,
            date_from=now - timedelta(hours=3),
            date_to=now - timedelta(hours=1),
        )

        assert [tc.tool_name for tc in result.tool_calls] == ["inside"]
        assert result.truncated is False

    def test_truncated_flag_set_when_more_than_limit_events_exist(self) -> None:
        # With the row cap patched to 3 the helper only has to insert 4 events to
        # observe truncation, keeping the test fast.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        for index in range(4):
            self._capture_mcp_tool_call(session_id, f"tool_{index}", timestamp=now - timedelta(minutes=10 - index))
        flush_persons_and_events()

        with patch("products.mcp_analytics.backend.logic.MCP_TOOL_CALLS_RESULT_LIMIT", 3):
            result = api.list_mcp_tool_calls(self.team, session_id=session_id)

        assert len(result.tool_calls) == 3
        assert result.truncated is True

    def test_returns_empty_list_when_session_has_no_events(self) -> None:
        flush_persons_and_events()
        result = api.list_mcp_tool_calls(self.team, session_id=str(uuid7()))
        assert result.tool_calls == []
        assert result.truncated is False

    def test_view_returns_400_on_invalid_date_from(self) -> None:
        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_analytics/sessions/{str(uuid7())}/tool_calls/",
            data={"date_from": "not-a-date"},
        )
        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "Expected an ISO 8601 datetime, got 'not-a-date'.",
            "attr": "date_from",
        }

    def test_view_returns_truncated_field_in_response(self) -> None:
        session_id = str(uuid7())
        self._capture_mcp_tool_call(session_id, "query_run", timestamp=datetime.now(tz=UTC) - timedelta(minutes=5))
        flush_persons_and_events()

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/sessions/{session_id}/tool_calls/")
        assert response.status_code == 200
        body = response.json()
        assert body["truncated"] is False
        assert len(body["results"]) == 1
        assert body["results"][0]["tool_name"] == "query_run"
