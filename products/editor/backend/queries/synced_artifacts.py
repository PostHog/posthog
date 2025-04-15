from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedSyncedArtifactsQueryResponse,
    SyncedArtifactsQuery,
    SyncedArtifactsQueryResponse,
    SyncedArtifactsResponseItem,
)


class DistinctSyncedArtifactsQuery:
    def __init__(self, user_id: int, codebase_id: str, artifact_ids: list[str] | None = None):
        self.user_id = user_id
        self.codebase_id = codebase_id
        self.artifact_ids = artifact_ids

    def to_query(self) -> ast.SelectQuery:
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    artifact_id AS synced_artifact_id,
                    argMax(is_deleted, timestamp) AS deleted
                FROM
                    codebase_embeddings
                GROUP BY
                    artifact_id
                HAVING
                    deleted = 0
                """
            ),
        )
        query.where = self._get_where_clause()
        return query

    def _get_where_clause(self) -> ast.Expr:
        where_clause = [
            parse_expr("user_id = {user_id}", placeholders={"user_id": ast.Constant(value=self.user_id)}),
            parse_expr(
                "codebase_id = {codebase_id}", placeholders={"codebase_id": ast.Constant(value=self.codebase_id)}
            ),
        ]

        if self.artifact_ids:
            where_clause.append(
                parse_expr(
                    "artifact_id IN {artifact_ids}",
                    placeholders={
                        "artifact_ids": ast.Array(
                            exprs=[ast.Constant(value=artifact_id) for artifact_id in self.artifact_ids]
                        ),
                    },
                )
            )

        return ast.And(exprs=where_clause)


class SyncedArtifactsQueryRunner(QueryRunner):
    query: SyncedArtifactsQuery
    response: SyncedArtifactsQueryResponse
    cached_response: CachedSyncedArtifactsQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="SyncedArtifactsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[SyncedArtifactsResponseItem] = []
        for row in response.results:
            results.append(SyncedArtifactsResponseItem(id=row[0]))

        return SyncedArtifactsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return DistinctSyncedArtifactsQuery(
            user_id=self.query.userId,
            codebase_id=self.query.codebaseId,
            artifact_ids=self.query.artifactIds,
        ).to_query()
