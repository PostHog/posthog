from datetime import datetime, timedelta
from typing import cast

from django.db import connection
from django.db.models.aggregates import Max

import structlog
from pydantic import BaseModel
from rest_framework.exceptions import NotFound

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

from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

logger = structlog.get_logger(__name__)

DOCUMENT_TYPE = "fingerprint"


class SimilarFingerprint(BaseModel):
    fingerprint: str
    timestamp: datetime
    # Min distance with target issue fingerprints
    distance: float


class IssueWithSimilarFingerprints(BaseModel):
    team_id: int
    id: str
    name: str
    description: str
    status: str
    ## Holds only fps that are similar to the target issue fps (not all issue fingerprints)
    fingerprints: list[SimilarFingerprint]
    library: str | None

    def add_fingerprint(self, fingerprint: SimilarFingerprint):
        self.fingerprints.append(fingerprint)

    def set_library(self, library: str):
        self.library = library

    @property
    def first_fingerprint(self):
        return min(self.fingerprints, key=lambda f: f.timestamp)

    @property
    def closest_fingerprint(self):
        return min(self.fingerprints, key=lambda f: f.distance)

    def to_similar(self) -> SimilarIssue:
        return SimilarIssue(
            id=self.id,
            name=self.name,
            description=self.description,
            status=self.status,
            first_seen=self.first_fingerprint.timestamp.isoformat() if self.first_fingerprint else "",
            distance=self.closest_fingerprint.distance,
            library=self.library,
        )


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

    def _calculate(self):
        res: tuple[list[SimilarFingerprint], HogQLQueryResponse] = self.get_similar_fingerprints()
        similar_issues_fingerprints: list[IssueWithSimilarFingerprints] = self.get_similar_issues(res[0])
        self.enrich_issues(similar_issues_fingerprints)
        similar_issues = [
            issue_fp.to_similar() for issue_fp in similar_issues_fingerprints if issue_fp.id != self.query.issueId
        ]
        similar_issues.sort(key=lambda x: x.distance)
        return ErrorTrackingSimilarIssuesQueryResponse(
            results=similar_issues,
            modifiers=self.modifiers,
            timings=res[1].timings,
            hogql=res[1].hogql,
            **self.paginator.response_params(),
        )

    def get_similar_issues(self, similar_fingerprints: list[SimilarFingerprint]) -> list[IssueWithSimilarFingerprints]:
        fingerprint_strs: list[str] = [fingerprint.fingerprint for fingerprint in similar_fingerprints]
        fingerprints_by_id = {fingerprint.fingerprint: fingerprint for fingerprint in similar_fingerprints}
        similar_issues_by_id: dict[str, IssueWithSimilarFingerprints] = {}
        with connection.cursor() as cursor:
            cursor.execute(
                """ SELECT
                    fingerprints.fingerprint, issues.id, issues.name, issues.team_id, issues.description, issues.status
                    FROM (
                        SELECT DISTINCT ON (fingerprint)
                            fingerprint, issue_id, version, first_seen
                        FROM posthog_errortrackingissuefingerprintv2
                        WHERE fingerprint = ANY(%s)
                        ORDER BY fingerprint, version DESC
                    ) AS fingerprints
                    INNER JOIN posthog_errortrackingissue as issues ON issues.id = fingerprints.issue_id
                    WHERE issues.team_id = %s
                """,
                [fingerprint_strs, self.team.id],
            )
            similar_issues_by_id = {}
            for row in cursor.fetchall():
                fp, issue_id, name, team_id, description, status = row
                if issue_id not in similar_issues_by_id:
                    similar_issues_by_id[issue_id] = IssueWithSimilarFingerprints(
                        id=str(issue_id),
                        name=name,
                        team_id=team_id,
                        description=description,
                        status=status,
                        fingerprints=[],
                        library=None,
                    )
                similar_issues_by_id[issue_id].add_fingerprint(fingerprints_by_id[fp])

        return list(similar_issues_by_id.values())

    def enrich_issues(self, similar_issues: list[IssueWithSimilarFingerprints]):
        issues_by_fingerprint = {issue.closest_fingerprint.fingerprint: issue for issue in similar_issues}
        with self.timings.measure("error_tracking_first_event_fetching"):
            time_window = timedelta(days=1)
            fingerprint_conditions: list[ast.Expr] = [
                ast.And(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["timestamp"]),
                            right=ast.Constant(value=issue.closest_fingerprint.timestamp - time_window),
                            op=ast.CompareOperationOp.GtEq,
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=["timestamp"]),
                            right=ast.Constant(value=issue.closest_fingerprint.timestamp + time_window),
                            op=ast.CompareOperationOp.LtEq,
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                            right=ast.Constant(value=issue.closest_fingerprint.fingerprint),
                            op=ast.CompareOperationOp.Eq,
                        ),
                    ]
                )
                for issue in similar_issues
            ]
            global_time_conditions = ast.Or(exprs=fingerprint_conditions)
            query = ast.SelectQuery(
                select=[
                    ast.Field(chain=["properties", "$exception_fingerprint"]),
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
                group_by=[ast.Field(chain=["properties", "$exception_fingerprint"])],
            )
            results: HogQLQueryResponse = execute_hogql_query(query, team=self.team)
            for row in results.results:
                if row[0] in issues_by_fingerprint:
                    issues_by_fingerprint[row[0]].set_library(row[1])

    def get_similar_fingerprints(self) -> tuple[list[SimilarFingerprint], HogQLQueryResponse]:
        with self.timings.measure("error_tracking_similar_issues_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingSimilarIssuesQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
        similar_fingerprints = [
            SimilarFingerprint(fingerprint=row[0], timestamp=row[1], distance=row[2]) for row in query_result.results
        ]
        return (similar_fingerprints, query_result)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        matched_fingerprints = list(
            ErrorTrackingIssueFingerprintV2.objects.filter(
                team=self.team,
                issue_id=self.query.issueId,
            )
            .annotate(mversion=Max("version"))
            .values("fingerprint", "first_seen")
        )

        if len(matched_fingerprints) == 0:
            raise NotFound("No matching fingerprints found")
        ## Avoid edge cases because of clickhouse timestamp precision
        time_window = timedelta(minutes=1)
        min_timestamp = min(
            cast(datetime, fingerprint["first_seen"]) - time_window for fingerprint in matched_fingerprints
        )
        max_timestamp = max(
            cast(datetime, fingerprint["first_seen"]) + time_window for fingerprint in matched_fingerprints
        )
        target_fingerprints = [fingerprint["fingerprint"] for fingerprint in matched_fingerprints]
        return parse_select(
            self.query_template,
            placeholders={
                "fingerprints": ast.Constant(value=target_fingerprints),
                "model_name": ast.Constant(value=self.model_name),
                "rendering": ast.Constant(value=self.rendering),
                "max_distance": ast.Constant(value=self.max_distance),
                "min_target_timestamp": ast.Constant(value=min_timestamp),
                "max_target_timestamp": ast.Constant(value=max_timestamp),
                "limit": ast.Constant(value=self.query.limit),
            },
        )

    @property
    def query_template(self):
        return """
        SELECT fingerprint, argMin(timestamp, distance) as timestamp, min(distance) as distance
        FROM (
            SELECT
                b.document_id as fingerprint,
                b.timestamp as timestamp,
                cosineDistance(a.embedding, b.embedding) as distance
            FROM
            (
                SELECT document_id, embedding
                FROM document_embeddings
                WHERE document_type = 'fingerprint'
                AND rendering = {rendering}
                AND model_name = {model_name}
                AND document_id IN {fingerprints}
                AND product = 'error_tracking'
                AND timestamp >= {min_target_timestamp}
                AND timestamp <= {max_target_timestamp}
            ) as a
            CROSS JOIN (
                SELECT document_id, embedding, timestamp
                FROM document_embeddings
                WHERE document_type = 'fingerprint'
                AND rendering = {rendering}
                AND model_name = {model_name}
                AND document_id NOT IN {fingerprints}
                AND product = 'error_tracking'
            ) as b
            ORDER BY distance ASC
        ) as subquery
        WHERE subquery.distance <= {max_distance}
        GROUP BY fingerprint
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
