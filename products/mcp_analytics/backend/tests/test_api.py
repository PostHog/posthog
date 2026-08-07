import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.utils import uuid7
from posthog.utils import generate_cache_key

from products.mcp_analytics.backend import intent_generation, mcp_harness
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
        """Seed one $mcp_tool_call event per element of ``tool_sequence``.

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
                event="$mcp_tool_call",
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties={
                    "$session_id": session_id,
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

    def test_excludes_events_without_session_id(self) -> None:
        # Events with no $session_id (e.g. the bare-schema producers) must not
        # collapse into one empty-keyed "session".
        kept = str(uuid7())
        self._seed_session(kept, ["query_run"])
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
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

    def test_default_window_includes_sessions_within_seven_days(self) -> None:
        # Regression: the list previously used a fixed 24h lookback, so a session a few
        # days old showed on the 7d dashboard but vanished from this list. The default
        # window now matches the dashboard (DEFAULT_SESSIONS_DATE_FROM = '-7d').
        session_id = str(uuid7())
        three_days_ago = datetime.now(tz=UTC) - timedelta(days=3)
        self._seed_session(
            session_id,
            ["query_run"],
            session_start=three_days_ago,
            session_end=three_days_ago + timedelta(minutes=1),
        )

        results = {s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0).results}

        assert session_id in results

    def test_date_from_narrows_the_window(self) -> None:
        recent = str(uuid7())
        older = str(uuid7())
        now = datetime.now(tz=UTC)
        self._seed_session(
            recent,
            ["query_run"],
            session_start=now - timedelta(minutes=30),
            session_end=now - timedelta(minutes=29),
        )
        self._seed_session(
            older,
            ["query_run"],
            session_start=now - timedelta(hours=5),
            session_end=now - timedelta(hours=5) + timedelta(minutes=1),
        )

        within_1h = {
            s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0, date_from="-1h").results
        }
        within_7d = {
            s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0, date_from="-7d").results
        }

        assert recent in within_1h
        assert older not in within_1h
        assert {recent, older}.issubset(within_7d)

    def test_date_to_bounds_the_upper_end(self) -> None:
        now = datetime.now(tz=UTC)
        old = str(uuid7())
        new = str(uuid7())
        self._seed_session(
            old,
            ["query_run"],
            session_start=now - timedelta(days=3),
            session_end=now - timedelta(days=3) + timedelta(minutes=1),
        )
        self._seed_session(
            new,
            ["query_run"],
            session_start=now - timedelta(minutes=5),
            session_end=now - timedelta(minutes=4),
        )

        # Absolute window [7d ago, 2d ago] so neither bound is ambiguous: it spans the
        # 3-day-old session but ends before the 5-minute-old one.
        week_ago = (now - timedelta(days=7)).isoformat()
        two_days_ago = (now - timedelta(days=2)).isoformat()
        results = {
            s.session_id
            for s in api.list_mcp_sessions(
                self.team, limit=50, offset=0, date_from=week_ago, date_to=two_days_ago
            ).results
        }

        assert old in results
        assert new not in results

    def test_overlapping_session_reports_full_stats_not_clipped(self) -> None:
        # A session straddling the window start is included with its FULL stats: the event
        # before the window counts too, so start/duration/tool count span the whole session
        # rather than just the in-window slice.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._seed_session(
            session_id,
            ["query_run", "insight_get"],
            session_start=now - timedelta(hours=2),  # before the window
            session_end=now - timedelta(minutes=10),  # inside the window
        )

        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        sessions = [
            s
            for s in api.list_mcp_sessions(self.team, limit=50, offset=0, date_from=one_hour_ago).results
            if s.session_id == session_id
        ]

        assert len(sessions) == 1
        session = sessions[0]
        assert session.tool_calls == 2
        assert sorted(session.tools_used) == ["insight_get", "query_run"]
        # session_start is the pre-window event, not clipped up to the window start.
        assert session.session_start < now - timedelta(hours=1)

    def test_session_entirely_outside_window_is_excluded(self) -> None:
        # The buffered scan reads events just outside the window, but a session with no event
        # *inside* the window must not leak in via the buffer.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._seed_session(
            session_id,
            ["query_run"],
            session_start=now - timedelta(hours=3),
            session_end=now - timedelta(hours=2, minutes=59),
        )

        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        results = {
            s.session_id for s in api.list_mcp_sessions(self.team, limit=50, offset=0, date_from=one_hour_ago).results
        }

        assert session_id not in results

    def test_detail_shows_all_events_for_overlapping_session(self) -> None:
        # Clicking an overlapping session shows every event: the UI passes the full
        # session_start as the scan bound, so the pre-window event is included too.
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._seed_session(
            session_id,
            ["before_window", "in_window"],
            session_start=now - timedelta(hours=2),
            session_end=now - timedelta(minutes=10),
        )

        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        session = next(
            s
            for s in api.list_mcp_sessions(self.team, limit=50, offset=0, date_from=one_hour_ago).results
            if s.session_id == session_id
        )
        page = api.list_mcp_tool_calls(
            self.team, session_id=session_id, limit=500, offset=0, date_from=session.session_start
        )

        assert [c.tool_name for c in page.results] == ["before_window", "in_window"]


class TestGenerateIntentDigest(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _seed_intent_event(self, intent: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties={"$session_id": str(uuid7()), "$mcp_tool_name": "query_run", "$mcp_intent": intent},
        )

    def test_no_intents_returns_null_digest_without_llm(self) -> None:
        with patch.object(intent_generation, "summarize_project_intents") as mock_summarize:
            result = api.generate_intent_digest(self.team)

        assert result == contracts.IntentDigest(digest=None, intent_count=0)
        mock_summarize.assert_not_called()

    def test_generates_then_serves_from_cache_for_same_corpus(self) -> None:
        cache.clear()
        self._seed_intent_event("check the signups funnel")
        self._seed_intent_event("compare to last week")

        parsed = intent_generation.IntentThemesSchema(
            summary="Signup funnel investigation.",
            themes=[
                intent_generation.IntentThemeSchema(
                    name="Funnel checks",
                    description="Checking signup funnel conversion.",
                    intent_numbers=[1, 2],
                )
            ],
        )
        with patch.object(intent_generation, "summarize_project_intents", return_value=parsed) as mock_summarize:
            first = api.generate_intent_digest(self.team)
            again = api.generate_intent_digest(self.team)

        assert first.digest == "Signup funnel investigation."
        assert first.intent_count == 2
        assert first.themes[0].name == "Funnel checks"
        assert first.themes[0].intent_count == 2
        assert first.themes[0].tools == ["query_run"]
        assert again == first
        mock_summarize.assert_called_once()

    def test_serves_recent_digest_when_the_corpus_churns(self) -> None:
        cache.clear()
        self._seed_intent_event("check the signups funnel")
        parsed = intent_generation.IntentThemesSchema(
            summary="Signup funnel investigation.",
            themes=[intent_generation.IntentThemeSchema(name="Funnel checks", description="", intent_numbers=[1])],
        )

        with patch.object(intent_generation, "summarize_project_intents", return_value=parsed) as mock_summarize:
            first = api.generate_intent_digest(self.team)
            self._seed_intent_event("now something completely different")
            after_churn = api.generate_intent_digest(self.team)

        mock_summarize.assert_called_once()
        # Reports the corpus it was derived from, so the theme shares still add up.
        assert after_churn == first
        assert after_churn.intent_count == 1

    @parameterized.expand(
        [
            ("corpus_key", "mcp_intent_digest_v3/{corpus_hash}"),
            ("recent_key", "mcp_intent_digest_v3/recent"),
        ]
    )
    def test_regenerates_when_a_cached_payload_predates_the_current_shape(self, _name: str, key: str) -> None:
        cache.clear()
        self._seed_intent_event("check the signups funnel")
        corpus_hash = hashlib.sha256(b"check the signups funnel").hexdigest()
        cache.set(
            generate_cache_key(self.team.pk, key.format(corpus_hash=corpus_hash)),
            {"summary": "Stale.", "themes": [{"name": "Old shape", "share": 0.5}]},
            60,
        )
        parsed = intent_generation.IntentThemesSchema(
            summary="Fresh.",
            themes=[
                intent_generation.IntentThemeSchema(name="Funnel checks", description="", intent_numbers=[1]),
            ],
        )

        with patch.object(intent_generation, "summarize_project_intents", return_value=parsed):
            result = api.generate_intent_digest(self.team)

        assert result.digest == "Fresh."


class TestResolveIntentThemes(SimpleTestCase):
    CORPUS = [
        ("check the signups funnel", "query_run"),
        ("compare to last week", "query_run"),
        ("list the feature flags", "flag_list"),
    ]

    def _resolve(self, *themes: intent_generation.IntentThemeSchema) -> list[contracts.IntentTheme]:
        parsed = intent_generation.IntentThemesSchema(summary="Summary.", themes=list(themes))
        return intent_generation.resolve_themes(parsed, self.CORPUS)

    @staticmethod
    def _theme(name: str, numbers: list[int]) -> intent_generation.IntentThemeSchema:
        return intent_generation.IntentThemeSchema(name=name, description="Doing things.", intent_numbers=numbers)

    def test_derives_count_tools_and_example_from_the_corpus(self) -> None:
        themes = self._resolve(self._theme("Funnel checks", [1, 3]))

        assert themes[0].intent_count == 2
        assert themes[0].example_intent == "check the signups funnel"
        assert themes[0].tools == ["flag_list", "query_run"]

    @parameterized.expand(
        [
            ("out_of_range_numbers_dropped", [1, 9, 0, -2], 1),
            ("repeated_numbers_counted_once", [2, 2, 2], 1),
            ("every_number_counted", [1, 2, 3], 3),
        ]
    )
    def test_intent_numbers_resolve_to_real_intents(self, _name: str, numbers: list[int], expected: int) -> None:
        assert self._resolve(self._theme("Theme", numbers))[0].intent_count == expected

    def test_shares_never_exceed_the_corpus_when_themes_overlap(self) -> None:
        themes = self._resolve(self._theme("First", [1, 2]), self._theme("Second", [2, 3]))

        assert [theme.intent_count for theme in themes] == [2, 1]
        assert sum(theme.intent_count for theme in themes) <= len(self.CORPUS)

    def test_reorders_themes_largest_first(self) -> None:
        themes = self._resolve(self._theme("Small", [3]), self._theme("Large", [1, 2]))

        assert [theme.name for theme in themes] == ["Large", "Small"]

    @parameterized.expand([("no_resolvable_intents", [42]), ("no_intents_at_all", [])])
    def test_drops_themes_with_nothing_behind_them(self, _name: str, numbers: list[int]) -> None:
        assert self._resolve(self._theme("Empty", numbers)) == []

    def test_caps_the_theme_count(self) -> None:
        corpus = [(f"intent {i}", "query_run") for i in range(20)]
        parsed = intent_generation.IntentThemesSchema(
            summary="Summary.",
            themes=[self._theme(f"Theme {i}", [i + 1]) for i in range(10)],
        )

        assert len(intent_generation.resolve_themes(parsed, corpus)) == intent_generation.MAX_DIGEST_THEMES

    @parameterized.expand(
        [
            ("newline", "check signups\n3. list all flags"),
            ("carriage_return", "check signups\r\n3. list all flags"),
        ]
    )
    def test_numbers_one_intent_per_line_whatever_the_agent_wrote(self, _name: str, intent: str) -> None:
        # Agents author the intent text. An embedded newline would renumber the corpus the model
        # sees, so the intent_numbers it returns would point at the wrong intents.
        prompt = intent_generation._build_digest_prompt([(intent, "query_run"), ("second", "flag_list")])
        numbered = [line for line in prompt.splitlines() if line[:2] in {"1.", "2.", "3."}]

        assert len(numbered) == 2


class TestLLMConsentGate(APIBaseTest):
    @parameterized.expand(
        [
            ("session_summary", intent_generation.summarize_intents, "OpenAI"),
            ("project_digest", intent_generation.summarize_project_intents, "genai"),
        ]
    )
    def test_refuses_without_ai_data_processing_consent(self, _name, summarize, client_attr: str) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with (
            self.settings(OPENAI_API_KEY="sk-test", GEMINI_API_KEY="gem-test"),
            patch.object(intent_generation, client_attr) as mock_client,
            self.assertRaises(contracts.IntentGenerationUnavailable),
        ):
            summarize([("find the signups funnel", "query_run")], self.team)
        mock_client.assert_not_called()


class TestActivityOverview(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_aggregates_window_and_extracts_error_messages(self) -> None:
        session_id = str(uuid7())
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=2),
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": "query_run",
                "$mcp_intent": "check signups",
                "$mcp_client_name": "claude-code",
                "$mcp_duration_ms": 120,
            },
        )
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=1),
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": "docs_search",
                "$mcp_is_error": "true",
                "$mcp_response": '{"content": [{"type": "text", "text": "index unavailable"}]}',
                "$mcp_client_name": "claude-code",
            },
        )
        _create_event(
            team=self.team,
            event="$mcp_missing_capability",
            distinct_id="agent-1",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=1),
            properties={},
        )
        # Outside the 30-day window: must not count anywhere.
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            timestamp=datetime.now(tz=UTC) - timedelta(days=40),
            properties={"$session_id": str(uuid7()), "$mcp_tool_name": "query_run"},
        )

        overview = api.get_activity_overview(self.team)

        assert overview.stats == contracts.ActivityStats(
            total_calls=2,
            distinct_tools=2,
            distinct_sessions=1,
            distinct_clients=1,
            calls_with_intent=1,
            error_calls=1,
            missing_capability_reports=1,
        )
        assert {(row.tool, row.calls, row.errors) for row in overview.top_tools} == {
            ("query_run", 1, 0),
            ("docs_search", 1, 1),
        }
        assert overview.clients == [contracts.ActivityClientRow(client="Claude Code", calls=2)]
        assert [call.tool for call in overview.recent_calls] == ["docs_search", "query_run"]
        error_call = overview.recent_calls[0]
        assert error_call.is_error is True
        assert error_call.error_message == "index unavailable"
        assert overview.recent_calls[1].duration_ms == 120.0
        assert overview.recent_calls[1].intent == "check signups"

    def _emit_call(self, properties: dict[str, Any], count: int = 1) -> None:
        for _ in range(count):
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="agent-1",
                timestamp=datetime.now(tz=UTC) - timedelta(minutes=5),
                properties={"$session_id": str(uuid7()), "$mcp_tool_name": "query_run", **properties},
            )

    def test_merges_client_spellings_into_one_canonical_row(self) -> None:
        # One client reaches us under several spellings — different casing, and a proxied
        # name carrying mcp-remote's signature. Grouping on the raw property listed each as
        # its own row, so one client competed with itself for the top-N slots.
        # Separator variants ("Claude Code", "CLAUDE_CODE") are deliberately not merged:
        # no client emits them, and collapsing `[ ._-]` would destroy the surface tokens
        # the classifier matches on ("claude-code cli", "visual studio code").
        for client, count in [
            ("claude-code", 3),
            ("Claude-Code", 2),
            ("claude-code (via mcp-remote 0.1.37)", 1),
        ]:
            self._emit_call({"$mcp_client_name": client}, count)

        overview = api.get_activity_overview(self.team)

        assert overview.clients == [contracts.ActivityClientRow(client="Claude Code", calls=6)]

    def test_counts_one_client_reached_by_two_identity_signals_once(self) -> None:
        # Codex arrives both as a session-pinned clientInfo name and as a user-agent
        # surface. Those are two different tokens but one client, so counting tokens
        # would report "2 clients" next to a Clients card showing a single row.
        self._emit_call({"mcp_session_client_name": "codex-mcp-client"}, count=3)
        self._emit_call({"$mcp_client_user_agent": "openai-mcp/1.0.0 (Codex)"}, count=2)

        overview = api.get_activity_overview(self.team)

        assert overview.clients == [contracts.ActivityClientRow(client="OpenAI Codex", calls=5)]
        assert overview.stats.distinct_clients == 1

    @parameterized.expand(
        [
            # `$mcp_client_name` rides on `initialize` only, so a mid-session tool call
            # carries the session-pinned name instead. Reading the raw property alone left
            # every one of these unattributed.
            ("session_pinned_name", {"mcp_session_client_name": "codex-mcp-client"}, "OpenAI Codex"),
            # Codex's other spelling: the User-Agent surface. The generic `openai-mcp`
            # prefix used to swallow this and report it as plain "OpenAI".
            ("codex_user_agent_surface", {"$mcp_client_user_agent": "openai-mcp/1.0 (Codex)"}, "OpenAI Codex"),
            ("vendor_header", {"mcp_vendor_client": "ClaudeCode"}, "Claude Code"),
            ("oauth_client_name", {"$mcp_oauth_client_name": "cursor-vscode"}, "Cursor"),
            # An unrecognized client is still named — its own self-report beats "Other".
            ("unrecognized_named_verbatim", {"$mcp_client_name": "openclaw-bundle-mcp"}, "openclaw-bundle-mcp"),
            # ...and keeps its own capitalization: matching lower-cases the token, but the
            # name shown back is the one the client reported.
            ("unrecognized_keeps_casing", {"$mcp_client_name": "NexusAgent"}, "NexusAgent"),
            (
                "unrecognized_keeps_casing_via_session",
                {"mcp_session_client_name": "Concept Connectors"},
                "Concept Connectors",
            ),
            ("no_identity_at_all", {}, mcp_harness.UNIDENTIFIED_HARNESS_LABEL),
        ]
    )
    def test_attributes_clients_from_every_identity_signal(
        self, _name: str, properties: dict[str, Any], expected: str
    ) -> None:
        self._emit_call(properties, count=2)

        overview = api.get_activity_overview(self.team)

        assert overview.clients == [contracts.ActivityClientRow(client=expected, calls=2)]
        # The stat tile and the live feed resolve the caller the same way the card does,
        # so they can't disagree about who called: counting the raw property scored these
        # as zero known clients and left the feed's caller column blank.
        assert overview.stats.distinct_clients == (0 if expected == mcp_harness.UNIDENTIFIED_HARNESS_LABEL else 1)
        assert [call.client_name for call in overview.recent_calls] == [expected, expected]


class TestGenerateSessionIntent(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _seed_intent_event(self, session_id: str, intent: str, tool: str = "query_run") -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties={"$session_id": session_id, "$mcp_tool_name": tool, "$mcp_intent": intent},
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
        # $mcp_tool_call event without a $mcp_intent property.
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties={"$session_id": session_id, "$mcp_tool_name": "query_run"},
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


class TestListMCPToolCalls(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _seed_tool_call(self, session_id: str, *, timestamp: datetime, tool: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="seed",
            timestamp=timestamp,
            properties={"$session_id": session_id, "$mcp_tool_name": tool},
        )

    def test_has_next_signals_more_pages(self) -> None:
        session_id = str(uuid7())
        start = datetime.now(tz=UTC) - timedelta(minutes=5)
        for i, tool in enumerate(["first", "second", "third"]):
            self._seed_tool_call(session_id, timestamp=start + timedelta(seconds=i), tool=tool)

        # Over-fetch (limit+1) lets the first page know more exists without a count query;
        # calls come back in chronological order, so the two pages cover all three with no skips.
        first = api.list_mcp_tool_calls(self.team, session_id=session_id, limit=2, offset=0, date_from=start)
        assert [c.tool_name for c in first.results] == ["first", "second"]
        assert first.has_next is True

        second = api.list_mcp_tool_calls(self.team, session_id=session_id, limit=2, offset=2, date_from=start)
        assert [c.tool_name for c in second.results] == ["third"]
        assert second.has_next is False

    def test_pagination_is_stable_across_tied_timestamps(self) -> None:
        session_id = str(uuid7())
        ts = datetime.now(tz=UTC) - timedelta(minutes=5)
        # All four calls share a timestamp (a burst), so only the event_id tiebreaker gives a total
        # order — without it, the two offset pages could overlap or skip a boundary row.
        for tool in ["a", "b", "c", "d"]:
            self._seed_tool_call(session_id, timestamp=ts, tool=tool)

        first = api.list_mcp_tool_calls(self.team, session_id=session_id, limit=2, offset=0, date_from=ts)
        second = api.list_mcp_tool_calls(self.team, session_id=session_id, limit=2, offset=2, date_from=ts)
        event_ids = [c.event_id for c in first.results] + [c.event_id for c in second.results]

        # The two pages cover all four calls with no duplicates and no skips.
        assert len(set(event_ids)) == 4


class TestSessionEventsLookbackBound(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    """The session-detail queries (tool calls and intents alike) bound their scan to
    SESSION_EVENTS_LOOKBACK by default, or to an explicit date_from, so the events sort key can
    prune instead of reading the team's full history."""

    def _seed_tool_call(self, session_id: str, *, timestamp: datetime, tool: str, intent: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="seed",
            timestamp=timestamp,
            properties={"$session_id": session_id, "$mcp_tool_name": tool, "$mcp_intent": intent},
        )

    @parameterized.expand(
        [
            (
                "tool_calls",
                lambda self, sid: [
                    c.tool_name for c in api.list_mcp_tool_calls(self.team, session_id=sid, limit=500, offset=0).results
                ],
                ["recent_tool"],
            ),
            (
                "session_intents",
                lambda self, sid: intent_generation.fetch_session_intents(self.team, sid),
                ["recent intent"],
            ),
        ]
    )
    def test_excludes_events_older_than_lookback(self, _name, fetch, expected) -> None:
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        self._seed_tool_call(
            session_id, timestamp=now - timedelta(minutes=5), tool="recent_tool", intent="recent intent"
        )
        self._seed_tool_call(
            session_id,
            timestamp=now - intent_generation.SESSION_EVENTS_LOOKBACK - timedelta(days=1),
            tool="ancient_tool",
            intent="ancient intent",
        )

        assert fetch(self, session_id) == expected

    @parameterized.expand(
        [
            (
                "tool_calls",
                lambda self, sid, df: [
                    c.tool_name
                    for c in api.list_mcp_tool_calls(
                        self.team, session_id=sid, limit=500, offset=0, date_from=df
                    ).results
                ],
                ["ancient_tool"],
            ),
            (
                "session_intents",
                lambda self, sid, df: intent_generation.fetch_session_intents(self.team, sid, date_from=df),
                ["ancient intent"],
            ),
        ]
    )
    def test_date_from_override_includes_events_older_than_lookback(self, _name, fetch, expected) -> None:
        # Passing the session's own start as the bound (what the UI does) resolves events older than
        # the default fallback window, so any listed session stays openable / summarisable.
        session_id = str(uuid7())
        old_start = datetime.now(tz=UTC) - intent_generation.SESSION_EVENTS_LOOKBACK - timedelta(days=3)
        self._seed_tool_call(session_id, timestamp=old_start, tool="ancient_tool", intent="ancient intent")

        assert fetch(self, session_id, old_start - timedelta(minutes=1)) == expected
