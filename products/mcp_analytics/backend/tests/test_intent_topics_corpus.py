import json
from datetime import datetime, timedelta
from functools import partial

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.error_tracking.backend.indexed_embedding import DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL, EMBEDDING_TABLES
from products.event_definitions.backend.models import PropertyDefinition
from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.constants import EMBEDDING_MODEL
from products.mcp_analytics.backend.intent_topics.corpus import (
    DistinctIntent,
    fetch_seen_hashes,
    iter_distinct_intent_pages,
    iter_live_intent_pages,
    live_intent_embeddings_query,
)
from products.mcp_analytics.backend.intent_topics.pipeline import fetch_fit_sample
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
        self._call("list flags", tool="query-trends", at=WINDOW_START + timedelta(minutes=6))
        self._call("find retention", extra={"$mcp_intent_source": "context_parameter"})
        self._call("outside window", at=WINDOW_END + timedelta(minutes=1))
        self._call("", tool="query-trends")
        flush_persons_and_events()

        pages = self._fetch()

        assert pages == [
            sorted(
                [
                    DistinctIntent(
                        hash=intent_hash("list flags"),
                        text="list flags",
                        calls=2,
                        source_min_timestamp=WINDOW_START + timedelta(minutes=5),
                    ),
                    DistinctIntent(
                        hash=intent_hash("find retention"),
                        text="find retention",
                        calls=1,
                        source_min_timestamp=WINDOW_START + timedelta(minutes=5),
                    ),
                ],
                key=lambda i: i.hash,
            )
        ]
        assert set(DistinctIntent.__dataclass_fields__) == {"hash", "text", "calls", "source_min_timestamp"}

    def test_pages_through_every_intent_by_hash_without_a_cap(self) -> None:
        for i in range(5):
            for _ in range(5 - i):
                self._call(f"intent {i}")
        flush_persons_and_events()

        pages = self._fetch(page_size=2)

        assert [len(page) for page in pages] == [2, 2, 1]
        assert [intent for page in pages for intent in page] == sorted(
            (
                DistinctIntent(
                    hash=intent_hash(f"intent {n}"),
                    text=f"intent {n}",
                    calls=5 - n,
                    source_min_timestamp=WINDOW_START + timedelta(minutes=5),
                )
                for n in range(5)
            ),
            key=lambda i: i.hash,
        )

    def test_a_query_cut_short_by_a_limit_raises_instead_of_returning_a_partial_page(self) -> None:
        # A partial page would read as the last page, and the sync would mark the hour as drained.
        with patch(
            "products.mcp_analytics.backend.intent_topics.corpus.execute_hogql_query",
            wraps=execute_hogql_query,
        ) as execute:
            self._fetch()

        settings = execute.call_args.kwargs["settings"]
        assert (settings.timeout_overflow_mode, settings.read_overflow_mode) == ("throw", "throw")

    def test_live_embedding_payload_and_refit_weights_come_from_surviving_events(self) -> None:
        first = WINDOW_START + timedelta(minutes=5)
        self._call("list flags", at=first)
        self._call("list flags", at=first + timedelta(minutes=1))
        self._call("list flags", at=WINDOW_START - timedelta(days=40))
        self._call("expired only", at=WINDOW_START - timedelta(days=40))
        flush_persons_and_events()
        for text in ("list flags", "expired only", "erased source"):
            insert_intent_embedding(
                self.team.pk, intent_hash(text), "stale cached payload", at=WINDOW_START - timedelta(days=1), calls=99
            )
        insert_intent_embedding(OTHER_TEAM_ID, intent_hash("list flags"), "other team", at=WINDOW_START, calls=200)

        with patch("posthog.models.team.event_retention.events_retention_months_for_team", return_value=1):
            sources = [
                source
                for page in iter_live_intent_pages(
                    self.team, since=WINDOW_START - timedelta(days=50), until=WINDOW_END, page_size=1
                )
                for source in page
            ]
            query = live_intent_embeddings_query(self.team, sources, as_of=WINDOW_END)
            with (
                override_settings(CLICKHOUSE_EVENTS_OFFLINE_HOST="events.example.invalid"),
                events_route_scope(HogQLQueryModifiers(useNewEventsSchema=True)),
            ):
                rows = query.execute(self.team)
            sample = fetch_fit_sample(self.team, since=WINDOW_START - timedelta(days=50), until=WINDOW_END)

        assert [(row[0], row[1], row[2], row[3].replace(tzinfo=first.tzinfo)) for row in rows] == [
            (intent_hash("list flags"), "list flags", 2, first)
        ]
        assert sample.hashes == [intent_hash("list flags")]
        assert sample.texts == ["list flags"]
        assert sample.weights.tolist() == [2.0]

    def test_refit_pages_past_missing_vectors_and_keeps_a_bounded_deterministic_sample(self) -> None:
        texts = [f"intent {i}" for i in range(8)]
        for text in texts:
            self._call(text)
        flush_persons_and_events()
        ordered = sorted(texts, key=lambda text: intent_hash(intent_hash(text) + WINDOW_END.strftime("%Y%m%d")))
        for text in ordered[2:]:
            insert_intent_embedding(self.team.pk, intent_hash(text), "cached", at=WINDOW_START, calls=99)

        with patch(
            "products.mcp_analytics.backend.intent_topics.corpus.iter_live_intent_pages",
            wraps=partial(iter_live_intent_pages, page_size=2),
        ):
            sample = fetch_fit_sample(self.team, since=WINDOW_START, until=WINDOW_END, limit=3)

        assert sample.texts == ordered[2:5]
        assert sample.hashes == [intent_hash(text) for text in ordered[2:5]]
        assert sample.weights.tolist() == [1.0] * 3


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

    def test_reads_each_chunk_of_hashes_in_one_query(self) -> None:
        hashes = [intent_hash(f"seen {i}") for i in range(5)]
        for i, h in enumerate(hashes):
            insert_intent_embedding(self.team.pk, h, f"seen {i}", at=WINDOW_START - timedelta(days=1))

        with (
            patch("products.mcp_analytics.backend.intent_topics.corpus.HASH_CHUNK_SIZE", 3),
            patch(
                "products.mcp_analytics.backend.intent_topics.corpus.execute_hogql_query", wraps=execute_hogql_query
            ) as execute,
        ):
            seen = fetch_seen_hashes(self.team, [*hashes, intent_hash("never")], now=WINDOW_START)

        assert seen == set(hashes)
        assert execute.call_count == 2

    def test_empty_input_makes_no_query(self) -> None:
        assert fetch_seen_hashes(self.team, [], now=WINDOW_START) == set()


class TestIntentEmbeddingsAccess(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            (f"{name}_{months}", source, model_filter, content, months)
            for name, source, model_filter, content in [
                ("raw", "raw_document_embeddings AS e", f"model_name = '{EMBEDDING_MODEL}'", "content"),
                ("lazy", "document_embeddings AS e", f"model_name = '{EMBEDDING_MODEL}'", "content"),
                ("model", "posthog.document_embeddings_text_embedding_3_small_256 AS e", "1 = 1", "content"),
                (
                    "renamed",
                    "posthog.document_embeddings_text_embedding_3_small_256 AS e(p, dt, r, d, ts, ia, c, m, v)",
                    "1 = 1",
                    "c",
                ),
                (
                    "swapped",
                    "raw_document_embeddings AS e(document_type, product)",
                    f"model_name = '{EMBEDDING_MODEL}'",
                    "content",
                ),
            ]
            for months in (None, 1)
        ]
    )
    def test_source_provenance_gates_every_embedding_scan(
        self, _name: str, source: str, model_filter: str, content: str, months: int | None
    ) -> None:
        sync_execute(DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(replace=True))
        table = next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()
        cases = [
            (self.team.pk, "mcp_analytics", "mcp-intent", "fresh", WINDOW_START.isoformat()),
            (
                self.team.pk,
                "mcp_analytics",
                "mcp-intent",
                "expired",
                (WINDOW_START - timedelta(days=45)).isoformat(),
            ),
            (self.team.pk, "mcp_analytics", "mcp-intent", "unknown", None),
            (self.team.pk, "mcp_analytics", "mcp-intent", "malformed", "not a timestamp"),
            (self.team.pk, "error_tracking", "mcp-intent", "other product", None),
            (self.team.pk, "mcp_analytics", "other-document", "other document", None),
            (OTHER_TEAM_ID, "mcp_analytics", "mcp-intent", "other team", WINDOW_START.isoformat()),
        ]
        sync_execute(
            f"INSERT INTO {table} (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, metadata, embedding) VALUES",
            [
                (
                    team_id,
                    product,
                    document_type,
                    "raw",
                    intent_hash(text),
                    WINDOW_START,
                    WINDOW_START,
                    text,
                    json.dumps({"source_min_timestamp": provenance} if provenance is not None else {}),
                    [0.0] * 256,
                )
                for team_id, product, document_type, text, provenance in cases
            ],
        )
        expected = ["fresh", "other document", "other product"]
        if months is None:
            expected.append("expired")
        with patch("posthog.models.team.event_retention.events_retention_months_for_team", return_value=months):
            rows = execute_hogql_query(
                query=f"SELECT {content} AS payload FROM {source} WHERE {model_filter} ORDER BY payload",
                team=self.team,
            ).results
            count = execute_hogql_query(
                query=f"SELECT count() FROM {source} WHERE {model_filter}", team=self.team
            ).results

        assert rows == [(text,) for text in sorted(expected)]
        assert count == [(len(expected),)]

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

        assert rows() == [("fp-1", "TypeError in checkout", 256)]
        assert [matches(p) for p in predicates] == [0, 0, 0]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert rows() == sorted([("fp-1", "TypeError in checkout", 256), (intent, "list flags", 256)], key=str)
        assert [matches(p) for p in predicates] == [1, 1, 1]

    @parameterized.expand(
        [
            ("raw", "SELECT tuple(*) FROM raw_document_embeddings"),
            ("raw_alias", "SELECT tuple(e.*) FROM raw_document_embeddings AS e"),
            ("model_table", "SELECT tuple(*) FROM posthog.document_embeddings_text_embedding_3_small_256"),
            ("lazy", f"SELECT tuple(*) FROM document_embeddings WHERE model_name = '{EMBEDDING_MODEL}'"),
        ]
    )
    def test_a_member_denied_the_intent_property_cannot_read_embeddings_through_a_wildcard_argument(
        self, _name: str, sql: str
    ) -> None:
        # A wildcard inside a function argument is not expanded into fields, so the per-column mask cannot apply.
        sync_execute(DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(replace=True))
        insert_intent_embedding(self.team.pk, intent_hash("list flags"), "list flags", at=WINDOW_START)
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

        try:
            hidden = str(execute_hogql_query(query=sql, team=self.team, user=self.user).results)
        except QueryError:
            hidden = ""
        assert "list flags" not in hidden and intent_hash("list flags") not in hidden

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert intent_hash("list flags") in str(execute_hogql_query(query=sql, team=self.team, user=self.user).results)
