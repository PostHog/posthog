from django.db import models

import structlog

from posthog.schema import (
    CachedErrorTrackingSimilarIssuesQueryResponse,
    EmbeddingModelName,
    ErrorTrackingQueryResponse,
    ErrorTrackingSimilarIssuesQuery,
    ErrorTrackingSimilarIssuesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.error_tracking.backend.api.issues import ErrorTrackingIssueSerializer
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

logger = structlog.get_logger(__name__)

DOCUMENT_TYPE = "fingerprint"


class ErrorTrackingSimilarIssuesQueryRunner(AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingSimilarIssuesQuery
    cached_response: CachedErrorTrackingSimilarIssuesQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        ## Validate query

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        target_fingerprints = list(
            ErrorTrackingIssueFingerprintV2.objects.filter(
                team=self.team, issue_id__in=[self.query.issueId]
            ).values_list("fingerprint", flat=True)
        )
        logger.info(target_fingerprints)
        return parse_select(
            self.query_template,
            placeholders={
                "fingerprint": ast.Constant(value=target_fingerprints[0]),
                "model_name": ast.Constant(value=self.model_name),
                "rendering": ast.Constant(value=self.rendering),
                "max_distance": ast.Constant(value=self.max_distance),
            },
        )

    def _calculate(self):
        with self.timings.measure("error_tracking_similar_issues_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingSimilarIssuesQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = self.results(query_result.results)

        return ErrorTrackingSimilarIssuesQueryResponse(
            results=results.data,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def results(self, rows: list[tuple[str, float]]) -> ErrorTrackingIssueSerializer:
        similar_fingerprints = [row[0] for row in rows]
        issue_queryset = (
            ErrorTrackingIssue.objects.filter(team=self.team, fingerprints__fingerprint__in=similar_fingerprints)
            .select_related("assignment")
            .annotate(first_seen=models.Min("fingerprints__first_seen"))
            .distinct()
        )
        return ErrorTrackingIssueSerializer(issue_queryset, many=True)

    @property
    def query_template(self):
        return """
        SELECT
            b.document_id as fingerprint,
            MIN(cosineDistance(a.embedding, b.embedding)) as distance
        FROM
        (
            SELECT document_id, document_type, rendering, model_name, embedding
            FROM document_embeddings
            WHERE document_type = 'fingerprint'
            AND rendering = {rendering}
            AND model_name = {model_name}
            AND document_id = {fingerprint}
            AND product = 'error_tracking'
        ) as a
        JOIN document_embeddings as b
        ON a.document_type = b.document_type
        AND a.rendering = b.rendering
        AND a.model_name = b.model_name
        AND a.document_id != b.document_id
        GROUP BY fingerprint
        HAVING distance <= {max_distance}
        ORDER BY distance ASC
        """

    @property
    def model_name(self):
        return self.query.modelName or str(EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072)

    @property
    def rendering(self):
        return self.query.rendering or "type_message_and_stack"

    @property
    def max_distance(self):
        return self.query.maxDistance or 100
