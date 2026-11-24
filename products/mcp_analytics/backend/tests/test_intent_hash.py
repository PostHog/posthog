import hashlib

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from products.mcp_analytics.backend.intent_hash import INTENT_HASH_HOGQL, intent_hash


class TestIntentHash(ClickhouseTestMixin, APIBaseTest):
    def test_is_lowercase_sha256_hex_of_the_raw_text(self) -> None:
        text = "Find the retention insight for signups"
        assert intent_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert intent_hash(text) == intent_hash(text).lower()
        assert len(intent_hash(text)) == 64

    def test_hashes_the_untruncated_text(self) -> None:
        long_text = "x" * 5000
        assert intent_hash(long_text) != intent_hash(long_text[:1000])

    def test_python_and_hogql_agree_on_unicode_text(self) -> None:
        text = "Résumé – créer un tableau de bord 📊 for sign-ups"
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            properties={"$mcp_tool_name": "query-trends", "$mcp_intent": text},
        )
        flush_persons_and_events()

        response = execute_hogql_query(
            query=f"SELECT {INTENT_HASH_HOGQL} AS h FROM events WHERE event = '$mcp_tool_call'",
            team=self.team,
        )

        assert response.results == [(intent_hash(text),)]
