from datetime import datetime, timedelta

from django.db.models.aggregates import Max

import structlog

from posthog.schema import (
    CachedErrorTrackingSimilarIssuesQueryResponse,
    EmbeddingModelName,
    ErrorTrackingQueryResponse,
    ErrorTrackingSimilarIssuesQuery,
    ErrorTrackingSimilarIssuesQueryResponse,
    HogQLQueryResponse,
    SimilarIssue,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.error_tracking.backend.api.issues import ErrorTrackingIssuePreviewSerializer
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
        matched_fingerprints = list(
            ErrorTrackingIssueFingerprintV2.objects.filter(
                team=self.team,
                issue_id=self.query.issueId,
            )
            .annotate(mversion=Max("version"))
            .values("fingerprint")
        )
        target_fingerprints = [fingerprint["fingerprint"] for fingerprint in matched_fingerprints]
        return parse_select(
            self.query_template,
            placeholders={
                "fingerprints": ast.Constant(value=target_fingerprints),
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
        similar_fingerprints = [row[0] for row in query_result.results]
        similar_issues = self.fetch_issues(similar_fingerprints).data
        first_event_data = self.fetch_first_event_data(similar_issues)
        return ErrorTrackingSimilarIssuesQueryResponse(
            results=[
                SimilarIssue(
                    id=issue.get("id"),
                    name=issue.get("name"),
                    description=issue.get("description"),
                    first_seen=issue.get("first_seen"),
                    status=issue.get("status"),
                    library=first_event_data.get(issue.get("id"), None),
                )
                for issue in similar_issues
            ],
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def fetch_issues(self, similar_fingerprints: list[str]) -> ErrorTrackingIssuePreviewSerializer:
        issue_queryset = (
            ErrorTrackingIssue.objects.with_first_seen()
            .filter(team=self.team, fingerprints__fingerprint__in=similar_fingerprints)
            .distinct()
        )
        return ErrorTrackingIssuePreviewSerializer(issue_queryset, many=True)

    def fetch_first_event_data(self, similar_issues) -> dict[str, str]:
        time_points: list[datetime] = [datetime.fromisoformat(issue.get("first_seen")) for issue in similar_issues]
        time_window = timedelta(hours=1)
        time_conditions: list[ast.Expr] = [
            ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=time_point - time_window),
                        op=ast.CompareOperationOp.GtEq,
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=time_point + time_window),
                        op=ast.CompareOperationOp.LtEq,
                    ),
                ]
            )
            for time_point in time_points
        ]
        global_time_conditions = ast.Or(exprs=time_conditions)
        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["properties", "$exception_issue_id"]),
                ast.Call(name="Min", args=[ast.Field(chain=["properties", "$lib"])]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    global_time_conditions,
                    ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="$exception"),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ],
            ),
            group_by=[ast.Field(chain=["properties", "$exception_issue_id"])],
        )
        results: HogQLQueryResponse = execute_hogql_query(query, team=self.team)
        result_dict = {}
        for row in results.results:
            result_dict[row[0]] = row[1]
        return result_dict

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
            AND document_id IN {fingerprints}
            AND product = 'error_tracking'
        ) as a
        CROSS JOIN (
            SELECT document_id, document_type, rendering, model_name, embedding
            FROM document_embeddings
            WHERE document_type = 'fingerprint'
            AND rendering = {rendering}
            AND model_name = {model_name}
            AND document_id NOT IN {fingerprints}
            AND product = 'error_tracking'
        ) as b
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
        return self.query.maxDistance or 0.1
