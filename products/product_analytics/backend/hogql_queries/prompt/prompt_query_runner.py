from posthog.schema import CachedPromptQueryResponse, PromptQuery, PromptQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import QueryRunner


class PromptQueryRunner(QueryRunner[PromptQuery, PromptQueryResponse, CachedPromptQueryResponse]):
    """Runner for a prompt insight that has no generated viz yet.

    A `PromptQuery` whose `generatedQuery` snapshot is present is unwrapped to the inner
    query's native runner in `get_query_runner`, so it caches and renders exactly like the
    insight it generated. This runner only handles the empty case — it never calls an LLM
    (generation is a separate, explicitly invoked, gated, non-cached action).
    """

    query: PromptQuery
    response: PromptQueryResponse
    cached_response: CachedPromptQueryResponse

    def _calculate(self) -> PromptQueryResponse:
        return PromptQueryResponse(results=[])

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # No HogQL of its own; a trivial query keeps the cache-key/to_hogql machinery happy.
        return parse_select("SELECT 1")
