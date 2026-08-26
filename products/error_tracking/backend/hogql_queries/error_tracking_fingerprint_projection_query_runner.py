import math

from posthog.schema import (
    CachedErrorTrackingFingerprintProjectionQueryResponse,
    EmbeddingModelName,
    ErrorTrackingFingerprintProjectionPoint,
    ErrorTrackingFingerprintProjectionQuery,
    ErrorTrackingFingerprintProjectionQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param
from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

MAX_FINGERPRINTS = 250


@frozen
class FingerprintEmbedding:
    fingerprint: str
    embedding: list[float]


class ErrorTrackingFingerprintProjectionQueryRunner(
    ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingFingerprintProjectionQueryResponse]
):
    query: ErrorTrackingFingerprintProjectionQuery
    cached_response: CachedErrorTrackingFingerprintProjectionQueryResponse

    def __post_init__(self) -> None:
        self.query.issueId = validate_uuid_param(self.query.issueId, "issueId")

    def _calculate(self) -> ErrorTrackingFingerprintProjectionQueryResponse:
        selected_fingerprints, has_more = self._get_fingerprints()
        if not selected_fingerprints:
            return ErrorTrackingFingerprintProjectionQueryResponse(results=[], hasMore=False, modifiers=self.modifiers)

        with self.timings.measure("error_tracking_fingerprint_projection_hogql_execute"):
            query_result = execute_hogql_query(
                query=self._build_query(selected_fingerprints),
                team=self.team,
                user=self.user,
                query_type="ErrorTrackingFingerprintProjectionQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        embeddings_by_fingerprint = {item.fingerprint: item for item in _parse_embedding_rows(query_result.results)}
        ordered_embeddings = [
            embeddings_by_fingerprint[fingerprint]
            for fingerprint in selected_fingerprints
            if fingerprint in embeddings_by_fingerprint
        ]

        return ErrorTrackingFingerprintProjectionQueryResponse(
            results=project_fingerprint_embeddings(ordered_embeddings),
            hasMore=has_more,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        fingerprints, _ = self._get_fingerprints()
        return self._build_query(fingerprints)

    def _get_fingerprints(self) -> tuple[list[str], bool]:
        fingerprints = list(
            ErrorTrackingIssueFingerprintV2.objects.filter(team=self.team, issue_id=self.query.issueId)
            .order_by("created_at")
            .values_list("fingerprint", flat=True)[: MAX_FINGERPRINTS + 1]
        )
        return fingerprints[:MAX_FINGERPRINTS], len(fingerprints) > MAX_FINGERPRINTS

    def _build_query(self, fingerprints: list[str]) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT document_id, argMax(embedding, inserted_at) AS embedding
            FROM document_embeddings
            WHERE product = 'error_tracking'
              AND document_type = 'fingerprint'
              AND model_name = {model_name}
              AND rendering = {rendering}
              AND document_id IN {fingerprints}
            GROUP BY document_id
            """,
            placeholders={
                "fingerprints": ast.Constant(value=fingerprints),
                "model_name": ast.Constant(value=self.model_name),
                "rendering": ast.Constant(value=self.rendering),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise ValueError("Fingerprint projection query must be a SELECT query")
        return query

    @property
    def model_name(self) -> str:
        return self.query.modelName or str(EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072)

    @property
    def rendering(self) -> str:
        return self.query.rendering or "type_message_and_stack"


def project_fingerprint_embeddings(
    fingerprint_embeddings: list[FingerprintEmbedding],
) -> list[ErrorTrackingFingerprintProjectionPoint]:
    import numpy as np  # noqa: PLC0415 — keeps NumPy off unrelated error tracking query imports
    from sklearn.manifold import TSNE  # noqa: PLC0415 — keeps scikit-learn off unrelated query imports

    if not fingerprint_embeddings:
        return []
    if len(fingerprint_embeddings) == 1:
        item = fingerprint_embeddings[0]
        return [ErrorTrackingFingerprintProjectionPoint(fingerprint=item.fingerprint, x=0.0, y=0.0)]
    if len(fingerprint_embeddings) == 2:
        return [
            ErrorTrackingFingerprintProjectionPoint(fingerprint=fingerprint_embeddings[0].fingerprint, x=-1.0, y=0.0),
            ErrorTrackingFingerprintProjectionPoint(fingerprint=fingerprint_embeddings[1].fingerprint, x=1.0, y=0.0),
        ]

    embedding_matrix = np.asarray([item.embedding for item in fingerprint_embeddings], dtype=np.float64)
    if np.allclose(embedding_matrix, embedding_matrix[0]):
        return [
            ErrorTrackingFingerprintProjectionPoint(fingerprint=item.fingerprint, x=0.0, y=0.0)
            for item in fingerprint_embeddings
        ]
    coordinates = TSNE(
        n_components=2,
        perplexity=float(min(30, len(fingerprint_embeddings) - 1)),
        learning_rate="auto",
        init="random",
        metric="cosine",
        random_state=0,
    ).fit_transform(embedding_matrix)

    return [
        ErrorTrackingFingerprintProjectionPoint(
            fingerprint=item.fingerprint,
            x=float(coordinates[index, 0]),
            y=float(coordinates[index, 1]),
        )
        for index, item in enumerate(fingerprint_embeddings)
    ]


def _parse_embedding_rows(rows: list[list[object]]) -> list[FingerprintEmbedding]:
    parsed_rows: list[FingerprintEmbedding] = []
    for row in rows:
        if len(row) != 2 or not isinstance(row[0], str) or not isinstance(row[1], list):
            continue
        embedding = row[1]
        if not embedding or not all(isinstance(value, int | float) and math.isfinite(value) for value in embedding):
            continue
        parsed_rows.append(FingerprintEmbedding(fingerprint=row[0], embedding=[float(value) for value in embedding]))
    return parsed_rows
