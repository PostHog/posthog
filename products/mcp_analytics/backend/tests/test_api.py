from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.core.cache import cache

from posthog.models.utils import uuid7

from products.mcp_analytics.backend import intent_generation
from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPSession
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


def _sorted_uuid7s(n: int) -> list[str]:
    """Generate ``n`` uuid7 strings sorted lexicographically.

    Back-to-back ``uuid7()`` values share their millisecond prefix and carry
    62 random bits each, so the relative order of consecutive values is
    effectively a coin flip. Tests that rely on the ``session_id ASC``
    tiebreaker for a stable order on tied sort keys (e.g. equal
    ``session_end``) should pre-sort the IDs so the tiebreaker decides
    deterministically.
    """
    return sorted(str(uuid7()) for _ in range(n))


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


class TestListMCPSessions(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Listing results are cached briefly; clear so each test sees fresh data.
        cache.clear()

    def _seed_session(
        self,
        session_id: str,
        tool_sequence: list[str],
        *,
        client_name: str = "Claude Desktop",
        distinct_id: str = "anon_seed",
        session_start: datetime | None = None,
        session_end: datetime | None = None,
    ) -> None:
        """Seed one mcp_tool_call event per element of ``tool_sequence``.

        tool_call_count == len(tool_sequence); tools_used == its distinct values.
        Events span [session_start, session_end] so min/max timestamps line up.
        """
        now = datetime.now(tz=UTC)
        session_start = session_start or now - timedelta(minutes=5)
        session_end = session_end or now
        n = len(tool_sequence)
        span = session_end - session_start
        for i, tool in enumerate(tool_sequence):
            timestamp = session_end if n == 1 else session_start + span * (i / (n - 1))
            _create_event(
                team=self.team,
                event="mcp_tool_call",
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties={
                    "$mcp_session_id": session_id,
                    "$mcp_tool_name": tool,
                    "$mcp_client_name": client_name,
                },
            )

    def test_lists_sessions_in_newest_first_order(self) -> None:
        session_a = str(uuid7())
        session_b = str(uuid7())
        now = datetime.now(tz=UTC)

        self._seed_session(
            session_a,
            ["query_run", "insight_get"],
            session_start=now - timedelta(minutes=10),
            session_end=now - timedelta(minutes=8),
        )
        self._seed_session(
            session_b,
            ["dashboard_get", "query_run"],
            client_name="Cursor",
            session_start=now - timedelta(minutes=5),
            session_end=now - timedelta(minutes=4),
        )

        sessions = [
            s
            for s in api.list_mcp_sessions(self.team, limit=50, offset=0).results
            if s.session_id in {session_a, session_b}
        ]

        assert len(sessions) == 2
        # Newest session_start first
        assert sessions[0].session_id == session_b
        assert sessions[0].mcp_client_name == "Cursor"
        assert sorted(sessions[0].tools_used) == ["dashboard_get", "query_run"]
        # tool_calls is now the live event count, not a persisted total
        assert sessions[0].tool_calls == 2

        assert sessions[1].session_id == session_a
        assert sessions[1].mcp_client_name == "Claude Desktop"
        assert sorted(sessions[1].tools_used) == ["insight_get", "query_run"]
        assert sessions[1].tool_calls == 2

    def test_returns_empty_list_when_no_sessions(self) -> None:
        assert api.list_mcp_sessions(self.team, limit=50, offset=0).results == []

    def test_does_not_cache_empty_responses(self) -> None:
        # An empty result must not be cached, so a session created moments later
        # shows up immediately instead of being hidden by a cached empty list.
        assert api.list_mcp_sessions(self.team, limit=50, offset=0).results == []
        session_id = str(uuid7())
        self._seed_session(session_id, ["query_run"])

        page = api.list_mcp_sessions(self.team, limit=50, offset=0)

        assert [s.session_id for s in page.results] == [session_id]

    def test_excludes_events_without_mcp_session_id(self) -> None:
        # Events with no $mcp_session_id (e.g. the bare-schema producers) must not
        # collapse into one empty-keyed "session".
        kept = str(uuid7())
        self._seed_session(kept, ["query_run"])
        _create_event(
            team=self.team,
            event="mcp_tool_call",
            distinct_id="anon_noisy",
            timestamp=datetime.now(tz=UTC),
            properties={"$mcp_tool_name": "query_run"},
        )

        page = api.list_mcp_sessions(self.team, limit=50, offset=0)

        assert [s.session_id for s in page.results] == [kept]

    def test_search_filters_across_multiple_columns(self) -> None:
        alice_id = str(uuid7())
        bob_id = str(uuid7())
        misc_id = str(uuid7())

        self._seed_session(
            alice_id,
            ["query_run", "insight_get"],
            client_name="Claude Desktop",
            distinct_id="alice@hedgehog.dev",
        )
        self._seed_session(bob_id, ["dashboard_get"], client_name="Cursor", distinct_id="bob@example.com")
        self._seed_session(misc_id, ["feature_flag_get"], client_name="Windsurf", distinct_id="anon_dead")

        def search(term: str) -> set[str]:
            return {s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0, search=term).results}

        # distinct_id substring
        assert search("hedgehog") == {alice_id}
        # client name, case-insensitive
        assert search("CURSOR") == {bob_id}
        # tool name inside the tools_used array
        assert search("query_run") == {alice_id}
        # session_id substring — use suffix because uuid7 prefixes (timestamp) collide
        # when sessions are created microseconds apart.
        assert search(alice_id[-12:]) == {alice_id}
        # empty search returns everything we created
        assert {alice_id, bob_id, misc_id}.issubset(search(""))
        # no match
        assert search("zzzz") == set()

    def test_order_by_whitelist(self) -> None:
        # new_id and big_id share a session_end below, so the
        # order("session_end") assertion relies on the session_id ASC tiebreaker
        # to put new_id before big_id. Use the pre-sorted helper so that
        # invariant doesn't depend on luck from uuid7()'s 62 random bits.
        old_id, new_id, big_id = _sorted_uuid7s(3)
        now = datetime.now(tz=UTC)

        # tool_call_count == number of events; counts chosen so big > old > new.
        self._seed_session(
            old_id,
            ["query_run"] * 3,
            session_start=now - timedelta(minutes=120),
            session_end=now - timedelta(minutes=110),
        )
        self._seed_session(
            new_id,
            ["dashboard_get"],
            session_start=now - timedelta(minutes=20),
            session_end=now - timedelta(minutes=10),
        )
        # big_id starts in the middle but ends most recently (a long-running session), so
        # session_start order differs from session_end order — that's what proves the
        # default sorts by session_start, not session_end. session_end matches new_id's
        # on purpose: the assertion below exercises the session_id ASC tiebreaker.
        self._seed_session(
            big_id,
            ["insight_get"] * 5,
            session_start=now - timedelta(minutes=60),
            session_end=now - timedelta(minutes=10),
        )

        # Restrict to the three we just created so other rows don't interfere.
        target = {old_id, new_id, big_id}

        def order(value: str) -> list[str]:
            return [
                s.session_id
                for s in api.list_mcp_sessions(self.team, limit=50, offset=0, order_by=value).results
                if s.session_id in target
            ]

        # Default sort: newest session_start first (session_end DESC would give [big, new, old]).
        assert order("") == [new_id, big_id, old_id]
        # Ascending session_end
        assert order("session_end") == [old_id, new_id, big_id]
        # By tool_call_count desc
        assert order("-tool_call_count") == [big_id, old_id, new_id]
        # Unknown / unsafe column falls back to default
        assert order("password") == [new_id, big_id, old_id]
        assert order("-DROP TABLE") == [new_id, big_id, old_id]

    def test_has_next_signals_more_pages(self) -> None:
        # Identical session_end across all three so only the session_id tiebreaker
        # gives a stable order — the assertion below would flake without it.
        # IDs are pre-sorted so the tiebreaker resolves deterministically.
        ts = datetime.now(tz=UTC) - timedelta(minutes=5)
        ids = _sorted_uuid7s(3)
        for session_id in ids:
            self._seed_session(session_id, ["query_run"], session_start=ts, session_end=ts)

        # Over-fetch (limit+1) lets the first page know more exists without a count query.
        first = api.list_mcp_sessions(self.team, limit=2, offset=0)
        assert len(first.results) == 2
        assert first.has_next is True

        # Last page returns the remainder and reports no further pages.
        second = api.list_mcp_sessions(self.team, limit=2, offset=2)
        assert len(second.results) == 1
        assert second.has_next is False

        # With sorted IDs and the session_id ASC tiebreaker, pagination is a total
        # order — the two pages cover every session in id-ASC order, no skips/dupes.
        paged = [s.session_id for s in first.results] + [s.session_id for s in second.results]
        assert paged == ids


class TestGenerateSessionIntent(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _seed_intent_event(self, session_id: str, intent: str, tool: str = "query_run") -> None:
        _create_event(
            team=self.team,
            event="mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties={"$mcp_session_id": session_id, "$mcp_tool_name": tool, "$mcp_intent": intent},
        )

    def test_returns_cached_intent_without_calling_llm(self) -> None:
        session_id = str(uuid7())
        MCPSession.objects.create(team=self.team, session_id=session_id, intent="already summarised")

        with patch.object(intent_generation, "summarize_intents") as mock_summarize:
            result = api.generate_session_intent(self.team, session_id=session_id)

        assert result == "already summarised"
        mock_summarize.assert_not_called()

    def test_generates_persists_and_returns_summary(self) -> None:
        session_id = str(uuid7())
        self._seed_intent_event(session_id, "check the signups funnel")
        self._seed_intent_event(session_id, "compare to last week")

        with patch.object(
            intent_generation, "summarize_intents", return_value="Investigating signup funnel trends."
        ) as mock:
            result = api.generate_session_intent(self.team, session_id=session_id)

        assert result == "Investigating signup funnel trends."
        mock.assert_called_once()
        assert (
            MCPSession.objects.get(team=self.team, session_id=session_id).intent
            == "Investigating signup funnel trends."
        )

    def test_second_call_returns_persisted_without_regenerating(self) -> None:
        session_id = str(uuid7())
        self._seed_intent_event(session_id, "check the signups funnel")

        with patch.object(intent_generation, "summarize_intents", return_value="First summary.") as mock:
            api.generate_session_intent(self.team, session_id=session_id)
            again = api.generate_session_intent(self.team, session_id=session_id)

        assert again == "First summary."
        mock.assert_called_once()

    def test_no_recorded_intents_returns_message_without_calling_llm_or_persisting(self) -> None:
        session_id = str(uuid7())
        # mcp_tool_call event without a $mcp_intent property.
        _create_event(
            team=self.team,
            event="mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties={"$mcp_session_id": session_id, "$mcp_tool_name": "query_run"},
        )

        with patch.object(intent_generation, "summarize_intents") as mock_summarize:
            result = api.generate_session_intent(self.team, session_id=session_id)

        assert result == intent_generation.NO_INTENT_MESSAGE
        mock_summarize.assert_not_called()
        # Not persisted — the session stays retryable and the listing doesn't show a non-intent.
        assert not MCPSession.objects.filter(team=self.team, session_id=session_id).exists()

    def test_list_attaches_persisted_intent(self) -> None:
        session_id = str(uuid7())
        self._seed_intent_event(session_id, "raw per-call intent")
        MCPSession.objects.create(team=self.team, session_id=session_id, intent="Persisted summary.")

        sessions = [
            s for s in api.list_mcp_sessions(self.team, limit=50, offset=0).results if s.session_id == session_id
        ]

        assert len(sessions) == 1
        assert sessions[0].intent == "Persisted summary."
