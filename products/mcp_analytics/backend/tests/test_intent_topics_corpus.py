from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.corpus import fetch_distinct_intents, fetch_seen_hashes
from products.mcp_analytics.backend.tests.intent_topics_helpers import insert_intent_embedding

OTHER_TEAM_ID = 10**9  # never a real team in the test database, so rows cannot collide with the next test
WINDOW_START = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 19, 11, 0, tzinfo=UTC)


class TestFetchDistinctIntents(ClickhouseTestMixin, APIBaseTest):
    def _call(self, intent: str, tool: str = "query-trends", at: datetime | None = None, **extra: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            timestamp=at or WINDOW_START + timedelta(minutes=5),
            properties={"$mcp_tool_name": tool, "$mcp_intent": intent, "$mcp_source": "posthog_mcp_analytics", **extra},
        )

    def test_groups_calls_by_intent_text_with_counts_and_top_tool(self) -> None:
        self._call("list flags", tool="feature-flag-get-all")
        self._call("list flags", tool="feature-flag-get-all")
        self._call("list flags", tool="query-trends")
        self._call("find retention", tool="query-retention", **{"$mcp_intent_source": "context_parameter"})
        self._call("outside window", at=WINDOW_END + timedelta(minutes=1))
        self._call("", tool="query-trends")
        flush_persons_and_events()

        intents = fetch_distinct_intents(self.team, since=WINDOW_START, until=WINDOW_END)

        assert [(i.text, i.calls, i.top_tool) for i in intents] == [
            ("list flags", 3, "feature-flag-get-all"),
            ("find retention", 1, "query-retention"),
        ]
        assert intents[0].hash == intent_hash("list flags")
        assert intents[1].intent_source == "context_parameter"

    def test_resolves_the_effective_tool_behind_the_exec_wrapper(self) -> None:
        self._call("run sql", tool="exec", **{"$mcp_exec_verb": "call", "$mcp_exec_target_tool": "execute-sql"})
        flush_persons_and_events()

        intents = fetch_distinct_intents(self.team, since=WINDOW_START, until=WINDOW_END)

        assert [(i.text, i.top_tool) for i in intents] == [("run sql", "execute-sql")]

    def test_limit_keeps_the_most_called_intents(self) -> None:
        for _ in range(3):
            self._call("popular")
        self._call("rare")
        flush_persons_and_events()

        intents = fetch_distinct_intents(self.team, since=WINDOW_START, until=WINDOW_END, limit=1)

        assert [i.text for i in intents] == ["popular"]


class TestFetchSeenHashes(ClickhouseTestMixin, APIBaseTest):
    def test_returns_only_hashes_embedded_for_this_team_within_retention(self) -> None:
        fresh = intent_hash("fresh")
        stale = intent_hash("stale")
        insert_intent_embedding(self.team.pk, fresh, "fresh", at=WINDOW_START - timedelta(days=2))
        insert_intent_embedding(self.team.pk, stale, "stale", at=WINDOW_START - timedelta(days=45))
        insert_intent_embedding(OTHER_TEAM_ID, intent_hash("other team"), "other team", at=WINDOW_START)

        seen = fetch_seen_hashes(
            self.team, [fresh, stale, intent_hash("other team"), intent_hash("never")], now=WINDOW_START
        )

        assert seen == {fresh}

    def test_empty_input_makes_no_query(self) -> None:
        assert fetch_seen_hashes(self.team, [], now=WINDOW_START) == set()
