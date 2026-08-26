import json
import uuid

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.replay_vision.backend.embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT
from products.replay_vision.backend.search import ObservationSearchFilters, rank_observations


class TestObservationFiltersTagClause:
    """Pure-logic clause construction with no DB/ClickHouse, so it runs without the full test stack."""

    @parameterized.expand(
        [
            ("single", ["frustrated_or_confused"]),
            ("multiple", ["abandoned", "completed"]),
            # `where_clauses` registers values verbatim, pre-slugifying is `from_raw`'s job. The SQL
            # slugifies the *stored* side, so passing a non-slug here proves the value is not re-normalized.
            ("verbatim_not_renormalized", ["Frustrated Or Confused"]),
        ]
    )
    def test_tags_clause_normalizes_stored_side_and_registers_values(self, _name: str, tags: list[str]) -> None:
        placeholders: dict = {}
        clauses = ObservationSearchFilters(tags=tags).where_clauses(placeholders)

        assert len(clauses) == 1
        # Stored metadata tags are slugified inside the clause (arrayMap) so verbatim-stored tags still match.
        assert clauses[0].startswith("hasAny(")
        assert "arrayMap" in clauses[0]
        # The clause carries no inlined tag value. It lives only in the parameterized placeholder, verbatim.
        assert placeholders["tags"].value == tags


# Runs the ranking SQL against real ClickHouse. Everything else mocks `execute_hogql_query`.
class TestRankObservationsQuery(ClickhouseTestMixin, APIBaseTest):
    def _insert_embedding_rows(self, rows: list[tuple]) -> None:
        # Reads for this model route to its model-specific table. Named inline to avoid a cross-product import.
        sync_execute(
            """
            INSERT INTO distributed_posthog_document_embeddings_text_embedding_3_large_3072 (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            rows,
            flush=False,
            team_id=self.team.pk,
        )

    def test_ranks_dedupes_and_truncates_matched_content(self) -> None:
        scanner_id = str(uuid.uuid4())
        best = str(uuid.uuid4())
        other = str(uuid.uuid4())
        now = timezone.now()
        metadata = json.dumps({"scanner_id": scanner_id})

        # The table enforces length(embedding) = 3072.
        def vector(x: float, y: float) -> list[float]:
            return [x, y, *([0.0] * 3070)]

        def row(rendering: str, document_id: str, content: str, embedding: list[float]) -> tuple:
            return (
                self.team.pk,
                EMBEDDING_PRODUCT,
                EMBEDDING_DOCUMENT_TYPE,
                rendering,
                document_id,
                now,
                now,
                content,
                metadata,
                embedding,
                now,
                0,
                0,
            )

        self._insert_embedding_rows(
            [
                row("intent", best, "user wanted to check out", vector(1.0, 0.0)),
                row("outcome", best, "gave up at the payment step", vector(0.0, 1.0)),
                row("reasoning", other, "x" * 400, vector(0.6, 0.8)),
            ]
        )

        matches = rank_observations(
            self.team, self.user, [scanner_id], vector(1.0, 0.0), 10, ObservationSearchFilters()
        )

        self.assertEqual([m.observation_id for m in matches], [best, other])
        # `best` has two renderings and the hit carries the closest one's text.
        self.assertEqual(matches[0].matched_content, "user wanted to check out")
        self.assertAlmostEqual(matches[0].distance, 0.0, places=5)
        self.assertEqual(len(matches[1].matched_content), 300)

    def test_every_filter_clause_compiles_and_applies_inside_the_candidate_subquery(self) -> None:
        scanner_id = str(uuid.uuid4())
        kept = str(uuid.uuid4())
        dropped = str(uuid.uuid4())
        now = timezone.now()
        embedding = [1.0, *([0.0] * 3071)]

        def row(document_id: str, metadata: dict) -> tuple:
            return (
                self.team.pk,
                EMBEDDING_PRODUCT,
                EMBEDDING_DOCUMENT_TYPE,
                "reasoning",
                document_id,
                now,
                now,
                "some content",
                json.dumps({"scanner_id": scanner_id, **metadata}),
                embedding,
                now,
                0,
                0,
            )

        self._insert_embedding_rows(
            [
                row(kept, {"verdict": "yes", "score": 2.0, "tags": ["Abandoned Cart"]}),
                row(dropped, {"verdict": "no", "score": 0.5, "tags": ["other"]}),
            ]
        )

        matches = rank_observations(
            self.team,
            self.user,
            [scanner_id],
            embedding,
            10,
            ObservationSearchFilters.from_raw(verdict=["yes"], tags=["abandoned cart"], min_score=1.0, max_score=3.0),
        )

        self.assertEqual([m.observation_id for m in matches], [kept])
