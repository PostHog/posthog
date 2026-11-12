from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.error_tracking.backend.indexed_embedding import DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL, EMBEDDING_TABLES
from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.constants import EMBEDDING_MODEL
from products.mcp_analytics.backend.intent_topics.corpus import fetch_distinct_intents, fetch_seen_hashes
from products.mcp_analytics.backend.tests.intent_topics_helpers import insert_intent_embedding, recent_hour

OTHER_TEAM_ID = 10**9  # never a real team in the test database, so rows cannot collide with the next test
WINDOW_START = recent_hour(days_ago=2)
WINDOW_END = WINDOW_START + timedelta(hours=1)


class TestFetchDistinctIntents(ClickhouseTestMixin, APIBaseTest):
    def _call(
        self, intent: str, tool: str = "query-trends", at: datetime | None = None, extra: dict[str, str] | None = None
    ) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="agent-1",
            timestamp=at or WINDOW_START + timedelta(minutes=5),
            properties={
                "$mcp_tool_name": tool,
                "$mcp_intent": intent,
                "$mcp_source": "posthog_mcp_analytics",
                **(extra or {}),
            },
        )

    def test_groups_calls_by_intent_text_with_counts_and_top_tool(self) -> None:
        self._call("list flags", tool="feature-flag-get-all")
        self._call("list flags", tool="feature-flag-get-all")
        self._call("list flags", tool="query-trends")
        self._call("find retention", tool="query-retention", extra={"$mcp_intent_source": "context_parameter"})
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
        self._call("run sql", tool="exec", extra={"$mcp_exec_verb": "call", "$mcp_exec_target_tool": "execute-sql"})
        flush_persons_and_events()

        intents = fetch_distinct_intents(self.team, since=WINDOW_START, until=WINDOW_END)

        assert [(i.text, i.top_tool) for i in intents] == [("run sql", "execute-sql")]

    def test_pages_through_more_intents_than_one_query_returns(self) -> None:
        for i in range(5):
            for _ in range(5 - i):
                self._call(f"intent {i}")
        flush_persons_and_events()

        intents = fetch_distinct_intents(self.team, since=WINDOW_START, until=WINDOW_END, page_size=2)

        assert [(i.text, i.calls) for i in intents] == [(f"intent {n}", 5 - n) for n in range(5)]

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

    def test_returns_every_seen_hash_beyond_the_default_row_limit(self) -> None:
        hashes = [intent_hash(f"seen {i}") for i in range(150)]
        for i, h in enumerate(hashes):
            insert_intent_embedding(self.team.pk, h, f"seen {i}", at=WINDOW_START - timedelta(days=1))

        seen = fetch_seen_hashes(self.team, [*hashes, intent_hash("never")], now=WINDOW_START)

        assert seen == set(hashes)

    def test_empty_input_makes_no_query(self) -> None:
        assert fetch_seen_hashes(self.team, [], now=WINDOW_START) == set()


class TestIntentEmbeddingsAccess(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("lazy", f"SELECT document_id, content FROM document_embeddings WHERE model_name = '{EMBEDDING_MODEL}'"),
            ("model_table", "SELECT document_id, content FROM posthog.document_embeddings_text_embedding_3_small_256"),
            ("raw", f"SELECT document_id, content FROM raw_document_embeddings WHERE model_name = '{EMBEDDING_MODEL}'"),
        ]
    )
    def test_a_member_denied_the_intent_property_cannot_read_intent_rows_of_the_embedding_tables(
        self, _name: str, query: str
    ) -> None:
        sync_execute(DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(replace=True))
        insert_intent_embedding(self.team.pk, intent_hash("list flags"), "list flags", at=WINDOW_START)
        table = next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()
        sync_execute(
            f"INSERT INTO {table} (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, metadata, embedding) VALUES",
            [
                (
                    self.team.pk,
                    "error_tracking",
                    "fingerprint",
                    "plain",
                    "fp-1",
                    WINDOW_START,
                    WINDOW_START,
                    "TypeError in checkout",
                    "{}",
                    [0.0] * 256,
                )
            ],
        )
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$mcp_intent", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
        )

        def run(sql: str) -> list[tuple]:
            return execute_hogql_query(query=sql, team=self.team, user=self.user).results

        assert sorted(run(query), key=str) == sorted([("fp-1", "TypeError in checkout"), (None, None)], key=str)
        assert run(f"SELECT count() FROM ({query}) WHERE content = 'list flags'") == [(0,)]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert sorted(run(query), key=str) == sorted(
            [("fp-1", "TypeError in checkout"), (intent_hash("list flags"), "list flags")], key=str
        )
