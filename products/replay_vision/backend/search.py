"""Semantic search core over observation embeddings, shared by the HTTP API and the Max tool.

The write side (`embed_observation`) stamps each embedding row with the scanner id and the structured
outcome (monitor `verdict`, scorer `score`, classifier `tags`), so filtering and cosine ranking happen in
a single ClickHouse query here. Callers resolve scanner scope and access control themselves and pass the
readable scanner ids in.
"""

from dataclasses import dataclass
from typing import Any

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.scanner_access import accessible_observations
from products.replay_vision.backend.tags import clickhouse_slugify_sql, slugify_tag

# Default and hard cap on how many observations a search returns.
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
# Postgres-side hydration re-checks status and access and can drop ranked ids, so a caller that ranks
# exactly `limit` ids can come back short. Callers rank this many times their limit and slice the
# hydrated rows back down, so drops only shorten the response once they exceed the margin.
RANK_OVERFETCH_FACTOR = 3
# Cut inside the candidate subquery so full facet paragraphs are neither carried through the sort nor
# sent over the wire.
_MATCHED_CONTENT_MAX_CHARS = 300
# The cosine-distance scan is exact (brute-force), so cap how many of a team's most-recent embedding rows it
# ranks over. Set well above realistic per-team volume so it only bites a runaway team, keeping latency
# predictable without an HNSW index (which our mandatory tenant/scanner metadata filters wouldn't engage anyway).
_MAX_CANDIDATE_ROWS = 50_000

# Slugify each stored metadata tag before `hasAny`, so the case/format-insensitive match works against rows
# whose fixed-vocab tags were stamped verbatim, with no backfill. The caller passes already-slugified values in
# `{tags}`. Built from hardcoded literals only (no user/LLM input), preserving the `_append_filter` invariant.
_TAGS_FILTER_CLAUSE = (
    f"hasAny(arrayMap(t -> {clickhouse_slugify_sql('t')}, JSONExtract(metadata, 'tags', 'Array(String)')), {{tags}})"
)


@dataclass(frozen=True)
class ObservationMatch:
    """One ranked search hit: the observation id and its cosine distance to the query (lower is closer)."""

    observation_id: str
    distance: float
    # Excerpt of the row that ranked this hit. Empty for rows written before `content` was stored.
    matched_content: str


@dataclass(frozen=True)
class ObservationSearchFilters:
    """Exact-outcome filters, applied inside the ClickHouse ranking query against the embedding metadata
    (monitor `verdict`, scorer `score`, classifier `tags` are stamped onto each embedding row at write time)."""

    verdict: list[str] | None = None
    tags: list[str] | None = None
    min_score: float | None = None
    max_score: float | None = None

    @classmethod
    def from_raw(
        cls,
        verdict: list[str] | None,
        tags: list[str] | None,
        min_score: float | None,
        max_score: float | None,
    ) -> "ObservationSearchFilters":
        """Normalize caller-supplied values: tags slugified to match the stored side, verdicts lowercased so
        a casing slip doesn't silently match nothing. Both are order-preserving deduped."""
        normalized_tags = list(dict.fromkeys(s for t in (tags or []) if (s := slugify_tag(t)))) or None
        normalized_verdict = list(dict.fromkeys(v.strip().lower() for v in (verdict or []) if v.strip())) or None
        return cls(verdict=normalized_verdict, tags=normalized_tags, min_score=min_score, max_score=max_score)

    def where_clauses(self, placeholders: dict[str, "ast.Expr"]) -> list[str]:
        """HogQL predicates over `metadata`, registering their values into `placeholders`. The metadata key is
        absent for scanner types that don't carry it, so each predicate naturally matches only the right type.

        Every clause MUST be added via `_append_filter`, the only path that pairs a hardcoded-literal
        clause string with a parameterized placeholder. Never append a clause built from anything other
        than a static string literal. User/LLM-controlled input belongs in `value`, not in `clause`."""
        clauses: list[str] = []
        if self.verdict:
            self._append_filter(
                clauses, placeholders, "verdict", self.verdict, "JSONExtractString(metadata, 'verdict') IN {verdict}"
            )
        if self.tags:
            self._append_filter(clauses, placeholders, "tags", self.tags, _TAGS_FILTER_CLAUSE)
        if self.min_score is not None:
            self._append_filter(
                clauses,
                placeholders,
                "min_score",
                self.min_score,
                "JSONHas(metadata, 'score') AND JSONExtractFloat(metadata, 'score') >= {min_score}",
            )
        if self.max_score is not None:
            self._append_filter(
                clauses,
                placeholders,
                "max_score",
                self.max_score,
                "JSONHas(metadata, 'score') AND JSONExtractFloat(metadata, 'score') <= {max_score}",
            )
        return clauses

    @staticmethod
    def _append_filter(
        clauses: list[str],
        placeholders: dict[str, "ast.Expr"],
        key: str,
        value: Any,
        clause: str,
    ) -> None:
        """Register one filter atomically: the value goes into `placeholders` (parameterized), the clause is
        the hardcoded literal that references it. The structure/value split lives in one place so callers
        can't half-do it. Any future filter must come through here, which makes the "clause is a static
        literal" invariant impossible to break by accident."""
        placeholders[key] = ast.Constant(value=value)
        clauses.append(clause)


def rank_observations(
    team: Team,
    user: User,
    scanner_ids: list[str],
    query_vector: list[float],
    limit: int,
    filters: ObservationSearchFilters,
) -> list[ObservationMatch]:
    """Closest observations by cosine distance, restricted to the given scanners and to the structured
    outcome filters via the embedding metadata, so filter and rank happen in a single query.

    `min(...)` collapses an observation's multiple renderings (the summarizer's per-facet rows) to its
    single best-matching distance, so each observation appears once.

    The distance scan is exact (brute-force), so we bound it: the inner query takes the most recent
    `_MAX_CANDIDATE_ROWS` matching embedding rows before ranking. Below that volume (all teams at launch
    scale) it's a no-op. A high-volume team is capped to its most recent embeddings, keeping latency
    predictable at the cost of not ranking its oldest observations.
    """
    placeholders: dict[str, ast.Expr] = {
        "embedding": ast.Constant(value=query_vector),
        "model_name": ast.Constant(value=OBSERVATION_EMBEDDING_MODEL.value),
        "product": ast.Constant(value=EMBEDDING_PRODUCT),
        "document_type": ast.Constant(value=EMBEDDING_DOCUMENT_TYPE),
        "team_id": ast.Constant(value=team.id),
        "scanner_ids": ast.Constant(value=scanner_ids),
        "candidate_cap": ast.Constant(value=_MAX_CANDIDATE_ROWS),
        "limit": ast.Constant(value=limit),
        "snippet_chars": ast.Constant(value=_MATCHED_CONTENT_MAX_CHARS),
    }
    filter_clause = "".join(f"\n                  AND {clause}" for clause in filters.where_clauses(placeholders))
    # The distance layer wraps the capped candidate subquery so the 3072-dim dot product runs once per
    # candidate row (min and argMin share the alias) and never on rows the cap already discarded.
    hogql_query = f"""
        SELECT
            document_id,
            min(row_distance) AS distance,
            argMin(snippet, row_distance) AS matched_content
        FROM (
            SELECT document_id, cosineDistance(embedding, {{embedding}}) AS row_distance, snippet
            FROM (
                SELECT document_id, embedding, substring(content, 1, {{snippet_chars}}) AS snippet
                FROM document_embeddings
                WHERE model_name = {{model_name}}
                  AND product = {{product}}
                  AND document_type = {{document_type}}
                  AND team_id = {{team_id}}
                  AND JSONExtractString(metadata, 'scanner_id') IN {{scanner_ids}}{filter_clause}
                ORDER BY timestamp DESC
                LIMIT {{candidate_cap}}
            )
        )
        GROUP BY document_id
        ORDER BY distance ASC
        LIMIT {{limit}}
    """
    tag_queries(product=Product.REPLAY_VISION, feature=Feature.SEMANTIC_SEARCH)
    result = execute_hogql_query(
        query=hogql_query,
        team=team,
        user=user,
        placeholders=placeholders,
        ch_user=ClickHouseUser.REPLAY_VISION,
    )
    return [
        ObservationMatch(observation_id=row[0], distance=row[1], matched_content=row[2])
        for row in (result.results or [])
    ]


def fetch_ranked_observations(
    team_id: int, scanner_ids: list[str], ordered_ids: list[str], access: UserAccessControl
) -> list[ReplayObservation]:
    """Hydrate ranked observation ids into rows, preserving rank order. The scanner-id filter and
    `accessible_observations` re-apply the caller's access scope here because embedding rows carry
    no experiment metadata, so a ranked id alone could leak an observation the caller can't read."""
    rows = ReplayObservation.objects.filter(
        team_id=team_id,
        scanner_id__in=scanner_ids,
        status=ObservationStatus.SUCCEEDED,
        id__in=ordered_ids,
    )
    rows = accessible_observations(access, team_id, rows).select_related("triggered_by_user", "label")
    observations = {str(obs.id): obs for obs in rows}
    return [obs for observation_id in ordered_ids if (obs := observations.get(observation_id)) is not None]
