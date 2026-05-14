from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

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
        # event_count is approximated by the size of tools_used
        assert sessions[0].event_count == 2

        assert sessions[1].session_id == session_a
        assert sessions[1].mcp_client_name == "Claude Desktop"
        assert sorted(sessions[1].tools_used) == ["insight_get", "query_run"]
        assert sessions[1].event_count == 2

    def test_returns_empty_list_when_no_sessions(self) -> None:
        assert api.list_mcp_sessions(self.team, limit=50, offset=0) == []
