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
        columns = ["artifact_id", "distance", "obfuscatedPath", "lineStart", "lineEnd"]
        for result in response.results:
            results.append(CodebaseTreeResponseItem(**{column: result[i] for i, column in enumerate(columns)}))

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
                argMax(artifact_id, timestamp) as artifact_id,
                argMax(parent_artifact_id, timestamp) as parent_artifact_id
            FROM
                codebase_catalog
            GROUP BY
                artifact_id
            WHERE
                is_deleted = 0 AND user_id = {user_id} AND codebase_id = {codebase_id} AND branch = {branch}
            """,
            placeholders={
                "user_id": ast.Constant(value=self.query.user_id),
                "codebase_id": ast.Constant(value=self.query.codebase_id),
                "branch": ast.Constant(value=self.query.branch),
            },
        )
