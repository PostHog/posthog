from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedEditorSemanticSearchQueryResponse,
    EditorSemanticSearchQuery,
    EditorSemanticSearchQueryResponse,
    EditorSemanticSearchResponseItem,
)


class EditorSemanticSearchQueryRunner(TaxonomyCacheMixin, QueryRunner):
    query: EditorSemanticSearchQuery
    response: EditorSemanticSearchQueryResponse
    cached_response: CachedEditorSemanticSearchQueryResponse

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

        results: list[EditorSemanticSearchResponseItem] = []
        columns = ["artifactId", "distance", "obfuscatedPath", "lineStart", "lineEnd"]
        for result in response.results:
            results.append(EditorSemanticSearchResponseItem(**{column: result[i] for i, column in enumerate(columns)}))

        return EditorSemanticSearchQueryResponse(
            results=results,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                argMax(vector, version) as artifact_id,
                cosineDistance(argMax(vector, version), {embedding}) as distance,
                argMax(properties.path, version) as obfuscatedPath,
                argMax(properties.lineStart, version) as lineStart,
                argMax(properties.lineEnd, version) as lineEnd
            FROM
                codebase_embeddings
            FINAL
            WHERE
                user_id = {user_id} AND codebase_id = {codebase_id} AND artifact_id IN {subquery}
            GROUP BY
                artifact_id
            ORDER BY
                distance ASC
            LIMIT 50
            """,
            placeholders={
                "user_id": ast.Constant(value=self.query.user_id),
                "codebase_id": ast.Constant(value=self.query.codebase_id),
                "embedding": ast.Constant(value=self.query.embedding),
            },
        )

    def subquery(self):
        # Joins are expensive, so we use a subquery to find all artifact IDs matching the query.
        return parse_select(
            """
            SELECT
                DISTINCT artifact_id as artifact_id
            FROM
                codebase_embeddings
            FINAL
            WHERE
                user_id = {user_id} AND codebase_id = {codebase_id} AND branch = {branch}
            """,
            placeholders={
                "user_id": ast.Constant(value=self.query.user_id),
                "codebase_id": ast.Constant(value=self.query.codebase_id),
                "branch": ast.Constant(value=self.query.branch),
            },
        )
