import dataclasses

from posthog.hogql import ast


@dataclasses.dataclass(frozen=True)
class EndpointPagination:
    limit: int
    offset: int
    ceiling: int | None

    def apply_to(self, select_query: ast.SelectQuery) -> None:
        """Set LIMIT and OFFSET on an AST SelectQuery for pagination."""
        if self.ceiling is not None and self.offset >= self.ceiling:
            select_query.limit = ast.Constant(value=0)
            select_query.offset = ast.Constant(value=0)
        else:
            remaining = (self.ceiling - self.offset) if self.ceiling is not None else None
            effective_limit = min(self.limit, remaining) if remaining is not None else self.limit
            select_query.limit = ast.Constant(value=effective_limit + 1)
            if self.offset > 0:
                select_query.offset = ast.Constant(value=self.offset)

    def process_results(self, result: dict) -> None:
        """Trim the extra row and annotate the result dict with pagination metadata."""
        rows = result.get("results", [])
        has_more = len(rows) > self.limit
        if has_more:
            result["results"] = rows[: self.limit]
        if self.ceiling is not None and self.offset + len(result["results"]) >= self.ceiling:
            has_more = False
        result["hasMore"] = has_more
        result["limit"] = self.limit
        result["offset"] = self.offset
