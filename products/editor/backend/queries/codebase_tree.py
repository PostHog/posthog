from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedCodebaseTreeQueryResponse,
    CodebaseTreeQuery,
    CodebaseTreeQueryResponse,
    CodebaseTreeResponseItem,
)


class CodebaseTreeQueryRunner(TaxonomyCacheMixin, QueryRunner):
    query: CodebaseTreeQuery
    response: CodebaseTreeQueryResponse
    cached_response: CachedCodebaseTreeQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="EditorSemanticSearchQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[CodebaseTreeResponseItem] = []
        for id, parent_id, artifact_type, synced in response.results:
            results.append(
                CodebaseTreeResponseItem(
                    id=id,
                    parentId=parent_id if parent_id else None,
                    type=artifact_type,
                    synced=synced,
                )
            )

        return CodebaseTreeQueryResponse(
            results=results,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                artifact_id,
                argMax(parent_artifact_id, timestamp) AS parent_artifact_id,
                argMax(type, timestamp) AS artifact_type,
                (artifact_type = 'dir' OR any(embeddings.synced_artifact_id) != '') AS synced
            FROM
                codebase_catalog
            LEFT JOIN (
                SELECT
                    argMax(DISTINCT artifact_id, version) AS synced_artifact_id
                FROM
                    codebase_embeddings
                WHERE
                    is_deleted = 0 AND user_id = {user_id} AND codebase_id = {codebase_id}
            ) AS embeddings
            ON
                codebase_catalog.artifact_id = embeddings.synced_artifact_id
            PREWHERE
                is_deleted = 0 AND user_id = {user_id} AND codebase_id = {codebase_id} AND branch = {branch}
            GROUP BY
                artifact_id
            """,
            placeholders={
                "user_id": ast.Constant(value=self.query.userId),
                "codebase_id": ast.Constant(value=self.query.codebaseId),
                "branch": ast.Constant(value=self.query.branch),
            },
        )
