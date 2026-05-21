from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from posthog.models.utils import uuid7

from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPSession
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


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


class TestListMCPSessions(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def _create_session(
        self,
        session_id: str,
        tools_used: list[str],
        client_name: str = "Claude Desktop",
        distinct_id: str = "anon_seed",
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
            distinct_id=distinct_id,
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

    def test_search_filters_across_multiple_columns(self) -> None:
        alice_id = str(uuid7())
        bob_id = str(uuid7())
        misc_id = str(uuid7())

        self._create_session(
            alice_id,
            tools_used=["query_run", "insight_get"],
            client_name="Claude Desktop",
            distinct_id="alice@hedgehog.dev",
        )
        self._create_session(
            bob_id,
            tools_used=["dashboard_get"],
            client_name="Cursor",
            distinct_id="bob@example.com",
        )
        self._create_session(
            misc_id,
            tools_used=["feature_flag_get"],
            client_name="Windsurf",
            distinct_id="anon_dead",
        )

        def search(term: str) -> set[str]:
            return {s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0, search=term)}

        # distinct_id substring
        assert search("hedgehog") == {alice_id}
        # client name, case-insensitive
        assert search("CURSOR") == {bob_id}
        # tool name inside the tools_used array
        assert search("query_run") == {alice_id}
        # session_id substring — use suffix because uuid7 prefixes (timestamp) collide
        # when sessions are created microseconds apart.
        assert search(alice_id[-12:]) == {alice_id}
        # empty search returns everything we created (DB may contain other rows from
        # earlier test runs if transactions aren't isolating; subset is enough).
        assert {alice_id, bob_id, misc_id}.issubset(search(""))
        # no match
        assert search("zzzz") == set()

    def test_order_by_whitelist(self) -> None:
        old_id = str(uuid7())
        new_id = str(uuid7())
        big_id = str(uuid7())
        now = datetime.now(tz=UTC)

        self._create_session(
            old_id,
            tools_used=["query_run"],
            session_start=now - timedelta(minutes=120),
            session_end=now - timedelta(minutes=110),
        )
        old_row = MCPSession.objects.get(session_id=old_id)
        old_row.tool_call_count = 3
        old_row.save(update_fields=["tool_call_count"])
        self._create_session(
            new_id,
            tools_used=["dashboard_get"],
            session_start=now - timedelta(minutes=20),
            session_end=now - timedelta(minutes=10),
        )
        new_row = MCPSession.objects.get(session_id=new_id)
        new_row.tool_call_count = 1
        new_row.save(update_fields=["tool_call_count"])
        self._create_session(
            big_id,
            tools_used=["insight_get"],
            session_start=now - timedelta(minutes=60),
            session_end=now - timedelta(minutes=50),
        )
        big_row = MCPSession.objects.get(session_id=big_id)
        big_row.tool_call_count = 99
        big_row.save(update_fields=["tool_call_count"])

        # Restrict to the three we just created so other rows don't interfere.
        target = {old_id, new_id, big_id}

        def order(value: str) -> list[str]:
            return [
                s.session_id
                for s in api.list_mcp_sessions(self.team, limit=50, offset=0, order_by=value)
                if s.session_id in target
            ]

        # Default sort: most-recent session_end first
        assert order("") == [new_id, big_id, old_id]
        # Ascending session_end
        assert order("session_end") == [old_id, big_id, new_id]
        # By tool_call_count desc
        assert order("-tool_call_count") == [big_id, old_id, new_id]
        # Unknown / unsafe column falls back to default
        assert order("password") == [new_id, big_id, old_id]
        assert order("-DROP TABLE") == [new_id, big_id, old_id]
