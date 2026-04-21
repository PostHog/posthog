from posthog.hogql import ast


def inject_series_index(query_ast: ast.SelectQuery | ast.SelectSetQuery) -> None:
    """Add a __series_index literal column to each sub-query in a UNION ALL.

    For single SelectQuery: adds ``0 AS __series_index``.
    For SelectSetQuery (multi-series UNION ALL): adds ``N AS __series_index``
    to each sub-query so the materialized table can distinguish series.
    """
    if isinstance(query_ast, ast.SelectQuery):
        _add_series_index_to_select(query_ast, 0)
    elif isinstance(query_ast, ast.SelectSetQuery):
        all_queries = query_ast.select_queries()
        for i, sub_query in enumerate(all_queries):
            if isinstance(sub_query, ast.SelectQuery):
                _add_series_index_to_select(sub_query, i)


def _add_series_index_to_select(query: ast.SelectQuery, index: int) -> None:
    """Add ``{index} AS __series_index`` to a single SELECT query."""
    series_col = ast.Alias(alias="__series_index", expr=ast.Constant(value=index))
    query.select = [*list(query.select or []), series_col]

    if query.group_by is not None:
        query.group_by = [*list(query.group_by), ast.Field(chain=["__series_index"])]
