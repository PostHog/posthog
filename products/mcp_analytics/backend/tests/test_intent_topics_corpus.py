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
from products.mcp_analytics.backend.intent_topics.corpus import (
    DistinctIntent,
    fetch_seen_hashes,
    iter_distinct_intent_pages,
)
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

    def _fetch(self, page_size: int = 10_000) -> list[list[DistinctIntent]]:
        return list(iter_distinct_intent_pages(self.team, since=WINDOW_START, until=WINDOW_END, page_size=page_size))

    def test_groups_calls_by_intent_text_and_copies_no_other_property(self) -> None:
        self._call("list flags", tool="feature-flag-get-all")
        self._call("list flags", tool="query-trends")
        self._call("find retention", extra={"$mcp_intent_source": "context_parameter"})
        self._call("outside window", at=WINDOW_END + timedelta(minutes=1))
        self._call("", tool="query-trends")
        flush_persons_and_events()

        pages = self._fetch()

        assert pages == [
            sorted(
                [
                    DistinctIntent(hash=intent_hash("list flags"), text="list flags", calls=2),
                    DistinctIntent(hash=intent_hash("find retention"), text="find retention", calls=1),
                ],
                key=lambda i: i.hash,
            )
        ]
        assert set(DistinctIntent.__dataclass_fields__) == {"hash", "text", "calls"}

    def test_pages_through_every_intent_by_hash_without_a_cap(self) -> None:
        for i in range(5):
            for _ in range(5 - i):
                self._call(f"intent {i}")
        flush_persons_and_events()

        pages = self._fetch(page_size=2)

        assert [len(page) for page in pages] == [2, 2, 1]
        assert [intent for page in pages for intent in page] == sorted(
            (DistinctIntent(hash=intent_hash(f"intent {n}"), text=f"intent {n}", calls=5 - n) for n in range(5)),
            key=lambda i: i.hash,
        )


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
            (
                "lazy",
                "document_embeddings",
                f"model_name = '{EMBEDDING_MODEL}'",
                ("document_id", "content", "embedding"),
            ),
            (
                "model_table",
                "posthog.document_embeddings_text_embedding_3_small_256",
                "1 = 1",
                ("document_id", "content", "embedding"),
            ),
            (
                "raw",
                "raw_document_embeddings",
                f"model_name = '{EMBEDDING_MODEL}'",
                ("document_id", "content", "embedding"),
            ),
            (
                "model_table_renamed_columns",
                "posthog.document_embeddings_text_embedding_3_small_256 AS e(p, dt, r, d, ts, ia, c, m, v)",
                "1 = 1",
                ("d", "c", "v"),
            ),
            (
                "raw_swapped_columns",
                "raw_document_embeddings AS e(document_type, product)",
                f"model_name = '{EMBEDDING_MODEL}'",
                ("document_id", "content", "embedding"),
            ),
        ]
    )
    def test_a_member_denied_the_intent_property_cannot_read_intent_rows_of_the_embedding_tables(
        self, _name: str, source: str, model_filter: str, columns: tuple[str, str, str]
    ) -> None:
        document_id, content, embedding = columns
        intent = intent_hash("list flags")
        sync_execute(DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(replace=True))
        insert_intent_embedding(self.team.pk, intent, "list flags", at=WINDOW_START)
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

        def rows() -> list[tuple]:
            sql = f"SELECT {document_id}, {content}, length({embedding}) FROM {source} WHERE {model_filter}"
            return sorted(run(sql), key=str)

        def matches(predicate: str) -> int:
            return run(f"SELECT count() FROM {source} WHERE {model_filter} AND {predicate}")[0][0]

        predicates = [f"{content} = 'list flags'", f"{document_id} = '{intent}'", f"{embedding}[1] = 1"]

        assert rows() == sorted([("fp-1", "TypeError in checkout", 256), (None, None, 0)], key=str)
        assert [matches(p) for p in predicates] == [0, 0, 0]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert rows() == sorted([("fp-1", "TypeError in checkout", 256), (intent, "list flags", 256)], key=str)
        assert [matches(p) for p in predicates] == [1, 1, 1]
